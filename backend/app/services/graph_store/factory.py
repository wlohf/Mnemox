"""Graph backend selection; SQL is the only Stage 4 runtime backend."""
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.graph_store.base import GraphStore
from app.services.graph_store.sql_store import SqlGraphStore


def create_graph_store(db: AsyncSession) -> GraphStore:
    return SqlGraphStore(db)
