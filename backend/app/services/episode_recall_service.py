"""Bounded entity-linked recall; canonical SQL text remains the answer evidence."""
import asyncio
import json
from copy import deepcopy
from app.config import settings
from app.models.understanding import UnderstandingPreference
from app.services.experience_service import live_experiences, public_experience
from app.services.graphiti_episode_service import create_episode_graph, meaningful, terms

MAX_GROUPS = 300


def chronology(row):
    # A reported local date is not replaced by its later import/update timestamp.
    return (row.payload.get('local_date') or str(row.occurred_at or row.recorded_at or row.first_seen_at), row.id)


async def graph_recall(graph, query, projections, limit):
    from graphiti_core.search.search_config import SearchConfig, EdgeSearchConfig, EdgeSearchMethod, EdgeReranker, NodeSearchConfig, NodeSearchMethod
    config = SearchConfig(
        edge_config=EdgeSearchConfig(search_methods=[EdgeSearchMethod.bm25], reranker=EdgeReranker.rrf),
        node_config=NodeSearchConfig(search_methods=[NodeSearchMethod.bm25]), limit=limit * 2)
    response = await graph.search_(query, config=config, group_ids=list(projections))
    seeds, anchors = set(), {}
    wanted = {t for t in terms(query) if len(t) > 1}
    for edge in response.edges:
        saved = projections.get(edge.group_id)
        if saved and any(e['uuid'] == edge.uuid for e in saved['edges']):
            seeds.add(edge.group_id)
    for node in response.nodes:
        saved = projections.get(node.group_id)
        if saved and any(n['uuid'] == node.uuid for n in saved['nodes']):
            seeds.add(node.group_id)
    # Only query-relevant entity names anchor expansion. A ubiquitous person or
    # "user" node must not connect every learning session to every question.
    for group in sorted(seeds):
        for node in projections[group]['nodes']:
            name = node['name'].strip().lower()
            if name not in {'user', 'learner', 'student', '用户', '学习者', '本人'} and wanted.intersection(terms(name)):
                anchors.setdefault(name, set()).add(group)
    anchors = dict(sorted(anchors.items())[:12])
    linked, connections = set(), []
    if anchors:
        records, _, _ = await graph.driver.execute_query(
            'MATCH (a:Entity)-[e:RELATES_TO]-(b:Entity) '
            'WHERE a.group_id IN $groups AND b.group_id = a.group_id '
            'AND e.group_id = a.group_id AND toLower(a.name) IN $names '
            'RETURN DISTINCT a.group_id AS group_id, a.uuid AS node_id, '
            'e.uuid AS edge_id, toLower(a.name) AS name '
            'ORDER BY group_id, edge_id LIMIT $cap',
            params={'groups': list(projections), 'names': list(anchors), 'cap': 96})
        for record in records:
            group, name = record['group_id'], record['name']
            saved = projections.get(group)
            if not saved or name not in anchors:
                continue
            if not any(n['uuid'] == record['node_id'] and n['name'].strip().lower() == name for n in saved['nodes']):
                continue
            if not any(e['uuid'] == record['edge_id'] and record['node_id'] in (e['source_node_uuid'], e['target_node_uuid']) for e in saved['edges']):
                continue
            linked.add(group)
            for origin in sorted(anchors[name] - {group}):
                connections.append({'from_group': origin, 'to_group': group, 'entity': name})
    return seeds, linked, connections


async def recall_episodes(db, user_id, query, *, limit=8, use_graph=True):
    query, limit = query[:500], max(1, min(limit, 20))
    live, incomplete = await live_experiences(db, user_id)
    live = [r for r in live if meaningful(r)]
    # Freeze identities before I/O: populate_existing may update ORM instances.
    versions = {r.id: r.source_version for r in live}
    pref = await db.get(UnderstandingPreference, user_id, populate_existing=True)
    preference_revision = pref.revision if pref else None
    status = {'backend': 'sql', 'reason': 'graphiti_episodes_disabled' if use_graph else 'sql_baseline',
              'graph_attempted': False, 'graph_hits': 0, 'truncated_kinds': sorted(incomplete)}
    graph, seeds, linked, connections = None, set(), set(), []
    rows = sorted([r for r in live if r.extraction and r.graph_group and not r.graph_pending], key=chronology, reverse=True)
    groups = {r.graph_group: r.id for r in rows[:MAX_GROUPS]}
    projections = {r.graph_group: deepcopy(r.extraction) for r in rows[:MAX_GROUPS]}
    status['graph_scope_truncated'] = len(rows) > MAX_GROUPS
    if use_graph and settings.GRAPHITI_EPISODES_ENABLED and pref and pref.graph_enabled:
        if groups:
            status['graph_attempted'] = True
            try:
                graph = create_episode_graph()
                seeds, linked, connections = await asyncio.wait_for(graph_recall(graph, query, projections, limit), timeout=4)
                status['reason'] = 'entity_linked_recall' if seeds or linked else 'graphiti_no_matching_edges'
            except Exception:
                seeds, linked, connections = set(), set(), []
                status['reason'] = 'graphiti_unavailable'
            finally:
                if graph:
                    try:
                        await graph.close()
                    except Exception:
                        pass  # Closing a failed read must not disable SQL fallback.
        else:
            status['reason'] = 'episode_projection_pending'
    checked, _ = await live_experiences(db, user_id)
    live = [r for r in checked if versions.get(r.id) == r.source_version and meaningful(r)]
    pref = await db.get(UnderstandingPreference, user_id, populate_existing=True)
    if (pref.revision if pref else None) != preference_revision:
        seeds, linked, connections = set(), set(), []
        status['reason'] = 'preferences_changed_during_retrieval'
    valid_ids = {r.id for r in live}
    seeds = {groups[g] for g in seeds if groups[g] in valid_ids}
    linked = {groups[g] for g in linked if groups[g] in valid_ids}
    wanted = set(terms(query))
    def rank(row):
        return (row.id in seeds | linked, len(wanted & set(terms(json.dumps(row.payload, ensure_ascii=False)))), chronology(row))
    ranked = sorted(live, key=rank, reverse=True)
    selected = ranked[:limit]
    # Reserve half of a graph-backed result for recent linked context so that a
    # later failed attempt cannot be crowded out by old exact keyword matches.
    recent = sorted([r for r in live if r.id in seeds | linked], key=chronology, reverse=True)[:max(1, limit // 2)]
    if recent:
        chosen = {r.id for r in recent}
        selected = recent + [r for r in ranked if r.id not in chosen][:limit-len(recent)]
    selected_ids = {r.id for r in selected}
    graph_ids = selected_ids & (seeds | linked)
    status.update(backend='graphiti_episode' if graph_ids else 'sql', graph_hits=len(graph_ids))
    if not graph_ids and status['reason'] == 'entity_linked_recall':
        status['reason'] = 'graph_sources_changed'
    connection_dtos, seen = [], set()
    for item in connections:
        left, right = groups[item['from_group']], groups[item['to_group']]
        key = (tuple(sorted((left, right))), item['entity'])
        if left in selected_ids and right in selected_ids and key not in seen:
            seen.add(key)
            connection_dtos.append({'from_id': left, 'to_id': right, 'entity': item['entity'], 'kind': 'shared_entity_index_hint'})
    def dto(row):
        return {**public_experience(row), 'retrieved_by': 'graphiti_episode' if row.id in graph_ids else 'sql_record',
                'match_kind': 'entity_neighbor' if row.id in linked - seeds else 'direct_match' if row.id in seeds else 'sql_lexical_or_recent'}
    return {**status, 'experiences': [dto(r) for r in selected], 'connections': connection_dtos,
        'timeline': [{'id': r.id, 'version': r.source_version,
            'local_date': r.payload.get('local_date'), 'occurred_at': r.payload.get('occurred_at'),
            'recorded_at': r.payload.get('recorded_at'), 'kind': r.kind} for r in sorted(selected, key=chronology)],
        'limitations': ['reported_experiences_not_permanent_traits', 'lexical_retrieval_not_semantic',
            'shared_entity_is_retrieval_hint_not_identity_or_causality', 'independent_episode_groups_no_automatic_cross_episode_truth_merge']}
