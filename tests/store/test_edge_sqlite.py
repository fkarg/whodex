"""SqliteEdgeStore satisfies the EdgeStore contract + durability."""

from __future__ import annotations

import tempfile
from pathlib import Path

from tests.store.edge_store_contract import EdgeStoreContract, _edge
from whodex.domain.enums import EdgeType
from whodex.store.sqlite import SqliteEdgeStore


class TestSqliteEdgeStore(EdgeStoreContract):
    def make_store(self) -> SqliteEdgeStore:
        return SqliteEdgeStore(url="sqlite://")


class TestSqliteEdgeStoreDurability:
    """Edges written to a real file survive across store instances."""

    def test_edges_survive_across_store_instances(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            url = f"sqlite:///{db_path}"

            store_a = SqliteEdgeStore(url=url)
            store_a.replace_edges([_edge("P", "Q", EdgeType.knows)])

            # New store instance pointing at same file
            store_b = SqliteEdgeStore(url=url)
            result = store_b.all_edges()
            assert len(result) == 1
            assert result[0].src_entity_id == "P"
            assert result[0].dst_entity_id == "Q"
            assert result[0].type == EdgeType.knows
