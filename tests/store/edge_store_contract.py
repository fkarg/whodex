"""Behavioural contract every EdgeStore must satisfy. Subclass and override make_store."""

from __future__ import annotations

from whodex.domain.enums import EdgeType
from whodex.domain.state import Edge


def _edge(src: str, dst: str, edge_type: EdgeType) -> Edge:
    """Helper: build a minimal Edge with an explicit id derived from its key fields."""
    eid = f"edge-{src}-{dst}-{edge_type.value}"
    return Edge(id=eid, src_entity_id=src, dst_entity_id=dst, type=edge_type)


class EdgeStoreContract:
    def make_store(self):  # override -> returns a fresh EdgeStore
        raise NotImplementedError

    # ── replace_edges + outgoing/incoming ────────────────────────────────────

    def test_replace_then_outgoing_returns_edge(self) -> None:
        s = self.make_store()
        e = _edge("A", "B", EdgeType.knows)
        s.replace_edges([e])
        result = s.outgoing("A")
        assert len(result) == 1
        assert result[0].src_entity_id == "A"
        assert result[0].dst_entity_id == "B"
        assert result[0].type == EdgeType.knows

    def test_replace_then_incoming_returns_edge(self) -> None:
        s = self.make_store()
        e = _edge("A", "B", EdgeType.knows)
        s.replace_edges([e])
        result = s.incoming("B")
        assert len(result) == 1
        assert result[0].src_entity_id == "A"
        assert result[0].dst_entity_id == "B"

    # ── filter by type ────────────────────────────────────────────────────────

    def test_outgoing_filtered_by_type_returns_matching(self) -> None:
        s = self.make_store()
        s.replace_edges(
            [
                _edge("A", "B", EdgeType.knows),
                _edge("A", "C", EdgeType.member_of),
            ]
        )
        result = s.outgoing("A", EdgeType.knows)
        assert len(result) == 1
        assert result[0].dst_entity_id == "B"

    def test_outgoing_filtered_by_type_excludes_non_matching(self) -> None:
        s = self.make_store()
        s.replace_edges(
            [
                _edge("A", "B", EdgeType.knows),
                _edge("A", "C", EdgeType.member_of),
            ]
        )
        result = s.outgoing("A", EdgeType.attended)
        assert result == []

    def test_incoming_filtered_by_type_returns_matching(self) -> None:
        s = self.make_store()
        s.replace_edges(
            [
                _edge("A", "Z", EdgeType.knows),
                _edge("B", "Z", EdgeType.member_of),
            ]
        )
        result = s.incoming("Z", EdgeType.knows)
        assert len(result) == 1
        assert result[0].src_entity_id == "A"

    def test_outgoing_no_filter_returns_all_types(self) -> None:
        s = self.make_store()
        s.replace_edges(
            [
                _edge("A", "B", EdgeType.knows),
                _edge("A", "C", EdgeType.member_of),
            ]
        )
        result = s.outgoing("A")
        assert len(result) == 2

    # ── replace is a full snapshot (drop old, no accumulation) ───────────────

    def test_replace_with_smaller_set_drops_old_edges(self) -> None:
        s = self.make_store()
        s.replace_edges(
            [
                _edge("A", "B", EdgeType.knows),
                _edge("A", "C", EdgeType.member_of),
            ]
        )
        # Replace with only one edge — the other must disappear
        s.replace_edges([_edge("A", "B", EdgeType.knows)])
        result = s.all_edges()
        assert len(result) == 1
        assert result[0].dst_entity_id == "B"

    def test_replace_empty_set_removes_all_edges(self) -> None:
        s = self.make_store()
        s.replace_edges([_edge("X", "Y", EdgeType.knows)])
        s.replace_edges([])
        assert s.all_edges() == []

    # ── idempotency: replacing the same set twice yields no duplicates ────────

    def test_replace_same_set_twice_no_duplicates(self) -> None:
        s = self.make_store()
        edges = [
            _edge("A", "B", EdgeType.knows),
            _edge("A", "C", EdgeType.member_of),
        ]
        s.replace_edges(edges)
        s.replace_edges(edges)
        result = s.all_edges()
        assert len(result) == 2

    def test_replace_same_edge_twice_yields_single_edge(self) -> None:
        s = self.make_store()
        e = _edge("A", "B", EdgeType.knows)
        s.replace_edges([e])
        s.replace_edges([e])
        result = s.all_edges()
        assert len(result) == 1

    # ── all_edges ──────────────────────────────────────────────────────────────

    def test_all_edges_empty_store_returns_empty(self) -> None:
        s = self.make_store()
        assert s.all_edges() == []

    def test_all_edges_returns_all_stored_edges(self) -> None:
        s = self.make_store()
        edges = [
            _edge("A", "B", EdgeType.knows),
            _edge("B", "C", EdgeType.member_of),
        ]
        s.replace_edges(edges)
        result = s.all_edges()
        assert len(result) == 2

    # ── outgoing/incoming for entity with no edges ─────────────────────────────

    def test_outgoing_unknown_entity_returns_empty(self) -> None:
        s = self.make_store()
        assert s.outgoing("NOBODY") == []

    def test_incoming_unknown_entity_returns_empty(self) -> None:
        s = self.make_store()
        assert s.incoming("NOBODY") == []
