"""SqliteProjectionStore satisfies the ProjectionStore contract + proves cross-instance durability."""

from __future__ import annotations

from tests.store.projection_store_contract import ProjectionStoreContract, _state
from whodex.store.sqlite import SqliteProjectionStore


class TestSqliteProjectionStore(ProjectionStoreContract):
    def make_store(self) -> SqliteProjectionStore:
        return SqliteProjectionStore(url="sqlite://")


def test_state_survives_across_store_instances(tmp_path):
    db = f"sqlite:///{tmp_path / 'p.db'}"
    SqliteProjectionStore(db).save({"E1": _state("E1", "Eng")})
    assert SqliteProjectionStore(db).load()["E1"].fields["job.title"].value == "Eng"
