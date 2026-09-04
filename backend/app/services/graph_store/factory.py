"""Explicit GraphStore backend selection for Stage 7.

SQL remains the default and canonical product path. Selecting Neo4j is an
operator choice, not a side effect of the historical shadow/enabled flags.
"""
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.graph_store.base import GraphStore
from app.services.graph_store.fallback_store import FallbackGraphStore
from app.services.graph_store.rollout_store import Neo4jRolloutGraphStore
from app.services.graph_store.sql_store import SqlGraphStore


def create_graph_store(db: AsyncSession) -> GraphStore:
    backend = str(settings.GRAPH_BACKEND or "sql").strip().lower()
    if backend == "sql":
        return SqlGraphStore(db)
    if backend == "neo4j":
        if not str(settings.NEO4J_PASSWORD or ""):
            raise RuntimeError("neo4j_graph_backend_not_configured")
        from app.services.graph_store.neo4j_store import Neo4jGraphStore, get_shared_neo4j_executor

        primary = Neo4jGraphStore(db, executor=get_shared_neo4j_executor())
        fallback = SqlGraphStore(db)
        resilient_primary = FallbackGraphStore(primary, fallback)
        return Neo4jRolloutGraphStore(
            db=db,
            primary=resilient_primary,
            fallback=fallback,
        )
    # Settings validates this in normal startup; keep the factory fail-closed for
    # tests/runtime mutation rather than silently selecting another backend.
    raise ValueError(f"unsupported_graph_backend:{backend}")
