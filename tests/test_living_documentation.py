"""Tests for LivingDocGenerator (Pillar 10)."""
from __future__ import annotations

import tempfile

import pytest
from core.living_documentation import (
    DocumentationPackage,
    LivingDocGenerator,
    get_doc_generator,
    reset_doc_generator,
)


@pytest.fixture(autouse=True)
def reset_gen() -> None:
    """Reset the singleton before each test."""
    reset_doc_generator()


@pytest.mark.slow
class TestLivingDocGenerator:
    """Tests for the LivingDocGenerator class."""

    def test_singleton(self) -> None:
        """Test singleton pattern."""
        d1 = get_doc_generator()
        d2 = get_doc_generator()
        assert d1 is d2

    def test_reset(self) -> None:
        """Test reset clears the singleton."""
        d1 = get_doc_generator()
        reset_doc_generator()
        d2 = get_doc_generator()
        assert d1 is not d2

    def test_generate_architecture_diagram(self) -> None:
        """Test generating architecture diagram."""
        doc = LivingDocGenerator()
        diagram = doc.generate_architecture_diagram()
        assert isinstance(diagram, str)
        assert len(diagram) > 50
        assert "mermaid" in diagram
        assert "graph TB" in diagram or "graph" in diagram

    def test_generate_er_diagram(self) -> None:
        """Test generating ER diagram."""
        doc = LivingDocGenerator()
        diagram = doc.generate_er_diagram()
        assert isinstance(diagram, str)
        assert "erDiagram" in diagram
        assert "trades" in diagram.lower()

    def test_generate_sequence_diagram_signal(self) -> None:
        """Test generating the signal flow sequence diagram."""
        doc = LivingDocGenerator()
        diagram = doc.generate_sequence_diagram("signal_flow")
        assert isinstance(diagram, str)
        assert "sequenceDiagram" in diagram
        assert "SignalEngine" in diagram

    def test_generate_sequence_diagram_trade(self) -> None:
        """Test generating the trade execution sequence diagram."""
        doc = LivingDocGenerator()
        diagram = doc.generate_sequence_diagram("trade_execution")
        assert "PositionSizer" in diagram

    def test_generate_sequence_diagram_risk(self) -> None:
        """Test generating the risk approval sequence diagram."""
        doc = LivingDocGenerator()
        diagram = doc.generate_sequence_diagram("risk_approval")
        assert "MandateEnforcer" in diagram

    def test_generate_sequence_diagram_incident(self) -> None:
        """Test generating the incident response sequence diagram."""
        doc = LivingDocGenerator()
        diagram = doc.generate_sequence_diagram("incident_response")
        assert "RootCauseAnalyzer" in diagram or "IncidentAlerting" in diagram

    def test_generate_sequence_diagram_unknown(self) -> None:
        """Test generating an unknown flow (falls back to default)."""
        doc = LivingDocGenerator()
        diagram = doc.generate_sequence_diagram("nonexistent_flow")
        assert isinstance(diagram, str)  # Falls back to default flow

    def test_generate_api_documentation(self) -> None:
        """Test generating API documentation."""
        doc = LivingDocGenerator()
        api_docs = doc.generate_api_documentation()
        assert isinstance(api_docs, str)
        assert "API Reference" in api_docs
        assert len(api_docs) > 100

    def test_generate_module_dependency_graph(self) -> None:
        """Test generating module dependency graph."""
        doc = LivingDocGenerator()
        graph = doc.generate_module_dependency_graph()
        assert isinstance(graph, str)
        assert "digraph" in graph

    def test_generate_deployment_diagram(self) -> None:
        """Test generating deployment diagram."""
        doc = LivingDocGenerator()
        diagram = doc.generate_deployment_diagram()
        assert isinstance(diagram, str)
        assert "mermaid" in diagram
        assert "Trading Engine" in diagram or "trader" in diagram.lower()

    def test_generate_all_to_temp(self) -> None:
        """Test generating all docs to a temp directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            doc = LivingDocGenerator(output_dir=tmpdir)
            pkg = doc.generate_all()
            assert isinstance(pkg, DocumentationPackage)
            assert pkg.n_files_generated >= 0
            assert pkg.architecture_mermaid != ""
            assert pkg.er_mermaid != ""
            assert pkg.sequence_mermaid != ""
            assert pkg.api_docs != ""

    def test_package_to_dict(self) -> None:
        """Test serialization of documentation package."""
        pkg = DocumentationPackage(
            generated_at="2026-01-01T00:00:00",
            n_files_generated=6,
        )
        d = pkg.to_dict()
        assert d["n_files_generated"] == 6
        assert d["generated_at"] == "2026-01-01T00:00:00"

    def test_get_stats_no_generation(self) -> None:
        """Test stats before any generation."""
        doc = LivingDocGenerator()
        stats = doc.get_stats()
        assert isinstance(stats, dict)
        assert "files_generated" in stats

    def test_fallback_architecture(self) -> None:
        """Test fallback architecture when KG is unavailable."""
        doc = LivingDocGenerator()
        fallback = doc._fallback_architecture()
        assert isinstance(fallback, str)
        assert "mermaid" in fallback

    def test_extract_docstring(self) -> None:
        """Test extracting docstrings from route handlers."""
        doc = LivingDocGenerator()
        content = '''
@app.get("/api/test")
async def test_handler():
    """Test endpoint description."""
    return {"status": "ok"}

@app.get("/api/sync")
def sync_handler():
    """Sync endpoint description."""
    return {"status": "ok"}
'''
        pos = content.index("@app.get")
        extracted = doc._extract_docstring(content, pos)
        assert "Test endpoint description" in extracted
