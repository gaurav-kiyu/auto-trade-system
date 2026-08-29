"""Tests for core/enterprise_knowledge_graph.py — Enterprise Knowledge Graph."""

from __future__ import annotations

from core.enterprise_knowledge_graph import (
    EnterpriseKGReport,
    EnterpriseKnowledgeGraph,
    KGNode,
    KGRelation,
    get_enterprise_knowledge_graph,
    reset_enterprise_knowledge_graph,
)


class TestKGNode:
    """KGNode dataclass."""

    def test_defaults(self):
        node = KGNode(node_id="test:1", name="Test Node", node_type="MODULE")
        assert node.node_id == "test:1"
        assert node.name == "Test Node"
        assert node.node_type == "MODULE"
        assert node.properties == {}
        assert node.weight == 1.0

    def test_with_properties(self):
        node = KGNode(
            node_id="module:core/test.py",
            name="test",
            node_type="MODULE",
            properties={"lines": 100, "symbols": 5},
            source="codebase",
            weight=0.5,
        )
        assert node.properties["lines"] == 100
        assert node.source == "codebase"

    def test_to_dict(self):
        node = KGNode(
            node_id="test:1",
            name="Test",
            node_type="MODULE",
            properties={"size": 50},
        )
        d = node.to_dict()
        assert d["node_id"] == "test:1"
        assert d["type"] == "MODULE"


class TestKGRelation:
    """KGRelation dataclass."""

    def test_fields(self):
        rel = KGRelation(
            source_id="module:a",
            target_id="module:b",
            relation_type="DEPENDS_ON",
        )
        assert rel.source_id == "module:a"
        assert rel.target_id == "module:b"
        assert rel.relation_type == "DEPENDS_ON"

    def test_with_weight(self):
        rel = KGRelation(
            source_id="a", target_id="b",
            relation_type="TESTS", weight=0.8,
        )
        assert rel.weight == 0.8

    def test_to_dict(self):
        rel = KGRelation(source_id="a", target_id="b", relation_type="DEPENDS_ON")
        d = rel.to_dict()
        assert d["source"] == "a"
        assert d["target"] == "b"
        assert d["type"] == "DEPENDS_ON"


class TestEnterpriseKGReport:
    """EnterpriseKGReport dataclass."""

    def test_defaults(self):
        report = EnterpriseKGReport()
        assert report.total_nodes == 0
        assert report.total_relations == 0

    def test_summary_text(self):
        report = EnterpriseKGReport(
            total_nodes=100,
            total_relations=200,
            by_type={"MODULE": 50, "TEST": 30},
            build_duration_ms=500.0,
        )
        text = report.summary_text()
        assert "100" in text
        assert "200" in text
        assert "MODULE" in text


class TestEnterpriseKnowledgeGraph:
    """EnterpriseKnowledgeGraph class."""

    def test_init(self):
        ekg = EnterpriseKnowledgeGraph()
        assert ekg is not None
        ekg.reset()

    def test_build_without_codebase_kg(self):
        """Should build with manual additions without crashing."""
        ekg = EnterpriseKnowledgeGraph()
        ekg._add_node(KGNode(node_id="module:test", name="Test", node_type="MODULE"))
        ekg._add_node(KGNode(node_id="doc:readme", name="README", node_type="DOCUMENT"))
        ekg._add_relation(KGRelation(source_id="module:test", target_id="doc:readme", relation_type="REFERENCES"))
        report = ekg.get_report()
        assert report.total_nodes == 2
        assert report.total_relations == 1
        ekg.reset()

    def test_search_after_build(self):
        ekg = EnterpriseKnowledgeGraph()
        ekg._add_node(KGNode(node_id="module:risk", name="RiskEngine", node_type="MODULE"))
        ekg._add_node(KGNode(node_id="module:test", name="TestRunner", node_type="MODULE"))
        results = ekg.search("risk")
        assert len(results) >= 1
        assert results[0].name == "RiskEngine"
        ekg.reset()

    def test_add_node_and_retrieve(self):
        ekg = EnterpriseKnowledgeGraph()
        ekg._add_node(KGNode(
            node_id="test:1", name="Test", node_type="MODULE",
        ))
        node = ekg.get_node("test:1")
        assert node is not None
        assert node.name == "Test"
        ekg.reset()

    def test_add_node_deduplicates(self):
        ekg = EnterpriseKnowledgeGraph()
        ekg._add_node(KGNode(
            node_id="test:1", name="First", node_type="MODULE",
        ))
        ekg._add_node(KGNode(
            node_id="test:1", name="Second", node_type="MODULE",
            properties={"extra": "data"},
        ))
        node = ekg.get_node("test:1")
        assert node.name == "First"  # Name not overwritten
        assert node.properties.get("extra") == "data"  # Properties merged
        ekg.reset()

    def test_add_and_query_relation(self):
        ekg = EnterpriseKnowledgeGraph()
        ekg._add_node(KGNode(node_id="a", name="A", node_type="MODULE"))
        ekg._add_node(KGNode(node_id="b", name="B", node_type="MODULE"))
        ekg._add_relation(KGRelation(
            source_id="a", target_id="b", relation_type="DEPENDS_ON",
        ))
        rels = ekg.get_relations("a")
        assert len(rels) == 1
        assert rels[0].relation_type == "DEPENDS_ON"
        ekg.reset()

    def test_get_relations_filtered(self):
        ekg = EnterpriseKnowledgeGraph()
        ekg._add_node(KGNode(node_id="a", name="A", node_type="MODULE"))
        ekg._add_node(KGNode(node_id="b", name="B", node_type="MODULE"))
        ekg._add_relation(KGRelation(source_id="a", target_id="b", relation_type="DEPENDS_ON"))
        ekg._add_relation(KGRelation(source_id="b", target_id="a", relation_type="REFERENCES"))
        rels = ekg.get_relations("a", relation_type="DEPENDS_ON")
        assert len(rels) == 1
        assert rels[0].relation_type == "DEPENDS_ON"
        ekg.reset()

    def test_get_connected_nodes(self):
        ekg = EnterpriseKnowledgeGraph()
        ekg._add_node(KGNode(node_id="a", name="A", node_type="MODULE"))
        ekg._add_node(KGNode(node_id="b", name="B", node_type="MODULE"))
        ekg._add_node(KGNode(node_id="c", name="C", node_type="MODULE"))
        ekg._add_relation(KGRelation(source_id="a", target_id="b", relation_type="DEPENDS_ON"))
        ekg._add_relation(KGRelation(source_id="b", target_id="c", relation_type="DEPENDS_ON"))
        connected = ekg.get_connected_nodes("a")
        assert len(connected) >= 2  # b (direct) and c (via b)
        ekg.reset()

    def test_get_connected_nodes_max_depth(self):
        ekg = EnterpriseKnowledgeGraph()
        ekg._add_node(KGNode(node_id="a", name="A", node_type="MODULE"))
        ekg._add_node(KGNode(node_id="b", name="B", node_type="MODULE"))
        ekg._add_node(KGNode(node_id="c", name="C", node_type="MODULE"))
        ekg._add_relation(KGRelation(source_id="a", target_id="b", relation_type="DEPENDS_ON"))
        ekg._add_relation(KGRelation(source_id="b", target_id="c", relation_type="DEPENDS_ON"))
        connected = ekg.get_connected_nodes("a", max_depth=1)
        node_ids = [n["node_id"] for n in connected]
        assert "b" in node_ids
        assert "c" not in node_ids  # 2 hops away
        ekg.reset()

    def test_get_stats(self):
        ekg = EnterpriseKnowledgeGraph()
        ekg._add_node(KGNode(node_id="a", name="A", node_type="MODULE"))
        ekg._add_node(KGNode(node_id="b", name="B", node_type="TEST"))
        stats = ekg.get_stats()
        assert stats["total_nodes"] == 2
        assert stats["by_type"]["MODULE"] == 1
        assert stats["by_type"]["TEST"] == 1
        ekg.reset()

    def test_get_report_after_build(self):
        ekg = EnterpriseKnowledgeGraph()
        ekg._add_node(KGNode(node_id="a", name="A", node_type="MODULE"))
        ekg._add_node(KGNode(node_id="b", name="B", node_type="TEST"))
        ekg._add_relation(KGRelation(source_id="a", target_id="b", relation_type="TESTS"))
        report = ekg.get_report()
        assert report.total_nodes == 2
        assert report.total_relations == 1
        ekg.reset()

    def test_orphan_detection(self):
        ekg = EnterpriseKnowledgeGraph()
        ekg._add_node(KGNode(node_id="a", name="A", node_type="MODULE"))
        ekg._add_node(KGNode(node_id="b", name="B", node_type="MODULE"))
        ekg._add_relation(KGRelation(source_id="a", target_id="b", relation_type="DEPENDS_ON"))
        ekg._add_node(KGNode(node_id="c", name="C", node_type="MODULE"))  # Orphan
        report = ekg.get_report()
        assert len(report.orphans) >= 1
        assert any("C" in o for o in report.orphans)
        ekg.reset()

    def test_relation_deduplication(self):
        ekg = EnterpriseKnowledgeGraph()
        ekg._add_node(KGNode(node_id="a", name="A", node_type="MODULE"))
        ekg._add_node(KGNode(node_id="b", name="B", node_type="MODULE"))
        # Add same relation twice
        ekg._add_relation(KGRelation(source_id="a", target_id="b", relation_type="DEPENDS_ON"))
        ekg._add_relation(KGRelation(source_id="a", target_id="b", relation_type="DEPENDS_ON"))
        rels = ekg.get_relations("a")
        assert len(rels) == 1  # Deduplicated
        ekg.reset()

    def test_persist_and_load(self, tmp_path):

        ekg = EnterpriseKnowledgeGraph()
        ekg._persist_path = tmp_path / "test_kg.json"

        ekg._add_node(KGNode(node_id="test:a", name="A", node_type="MODULE"))
        ekg._add_node(KGNode(node_id="test:b", name="B", node_type="TEST"))
        ekg._add_relation(KGRelation(source_id="test:a", target_id="test:b", relation_type="TESTS"))

        # Persist
        ekg._persist()

        # Create new instance and load
        ekg2 = EnterpriseKnowledgeGraph()
        ekg2._persist_path = tmp_path / "test_kg.json"
        loaded = ekg2.load()

        assert loaded is True
        assert ekg2.get_node("test:a") is not None
        assert ekg2.get_node("test:b") is not None
        rels = ekg2.get_relations("test:a")
        assert len(rels) >= 1
        ekg.reset()

    def test_config_nodes_created(self):
        ekg = EnterpriseKnowledgeGraph()
        # Manually add a config node
        ekg._add_node(KGNode(
            node_id="config:config.json",
            name="config.json",
            node_type="CONFIG",
            properties={"keys": 5},
            source="config",
        ))
        node = ekg.get_node("config:config.json")
        assert node is not None
        assert node.node_type == "CONFIG"
        ekg.reset()

    def test_search_by_type(self):
        ekg = EnterpriseKnowledgeGraph()
        ekg._add_node(KGNode(node_id="m:1", name="RiskEngine", node_type="MODULE"))
        ekg._add_node(KGNode(node_id="t:1", name="Risk", node_type="TEST"))
        results = ekg.search("risk")
        assert len(results) >= 2  # Both nodes match
        results_module = ekg.search("risk", node_type="MODULE")
        assert len(results_module) >= 1
        assert all(r.node_type == "MODULE" for r in results_module)
        ekg.reset()


class TestSingleton:
    """Singleton factory tests."""

    def test_get_and_reset(self):
        reset_enterprise_knowledge_graph()
        g1 = get_enterprise_knowledge_graph()
        g2 = get_enterprise_knowledge_graph()
        assert g1 is g2
        reset_enterprise_knowledge_graph()

    def test_reset_creates_new(self):
        reset_enterprise_knowledge_graph()
        g1 = get_enterprise_knowledge_graph()
        reset_enterprise_knowledge_graph()
        g2 = get_enterprise_knowledge_graph()
        assert g1 is not g2
