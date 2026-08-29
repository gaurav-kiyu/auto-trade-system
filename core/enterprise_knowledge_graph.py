"""Enterprise Knowledge Graph — Unified graph connecting codebase, business, incidents & documents.

Extends the CodebaseKnowledgeGraph with:
  - Business processes and workflows
  - Incidents and alerts (from IncidentCommandSystem)
  - Engineering decisions (from DecisionMemory)
  - Documentation files and ADRs
  - Configuration domains
  - Test coverage mapping
  - Infrastructure and deployment

This becomes your Enterprise Digital Twin — a single source of truth
connecting technical and business domains.

Usage:
    from core.enterprise_knowledge_graph import get_enterprise_knowledge_graph

    ekg = get_enterprise_knowledge_graph()
    ekg.build()
    report = ekg.get_report()
    print(report.summary_text())
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────

NODE_TYPES = [
    "MODULE", "SYMBOL", "API", "TEST", "DOCUMENT", "ADR",
    "CONFIG", "INCIDENT", "DECISION", "BUSINESS_PROCESS",
    "WORKFLOW", "DEPLOYMENT", "INFRASTRUCTURE", "DATABASE",
    "SCREEN", "PERMISSION", "USER_ROLE",
]

RELATION_TYPES = [
    "DEPENDS_ON", "IMPLEMENTS", "TESTS", "DOCUMENTS",
    "TRIGGERS", "RESOLVES", "AFFECTS", "REFERENCES",
    "DEPLOYS_TO", "CONFIGURES", "OWNS", "MONITORS",
]


# ── Data Models ───────────────────────────────────────────────────────────


@dataclass
class KGNode:
    """A node in the enterprise knowledge graph."""

    node_id: str
    name: str
    node_type: str
    properties: dict[str, Any] = field(default_factory=dict)
    source: str = ""  # Where this node came from (e.g., "codebase", "incident", "adr")
    weight: float = 1.0  # Importance/relevance weight

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "name": self.name,
            "type": self.node_type,
            "properties": {k: str(v)[:100] for k, v in self.properties.items()},
            "source": self.source,
            "weight": self.weight,
        }


@dataclass
class KGRelation:
    """A relationship between two nodes."""

    source_id: str
    target_id: str
    relation_type: str
    properties: dict[str, Any] = field(default_factory=dict)
    weight: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source_id,
            "target": self.target_id,
            "type": self.relation_type,
            "properties": self.properties,
            "weight": self.weight,
        }


@dataclass
class EnterpriseKGReport:
    """Complete enterprise knowledge graph report."""

    total_nodes: int = 0
    total_relations: int = 0
    by_type: dict[str, int] = field(default_factory=dict)
    by_source: dict[str, int] = field(default_factory=dict)
    top_connected_nodes: list[dict[str, Any]] = field(default_factory=list)
    orphans: list[str] = field(default_factory=list)
    build_duration_ms: float = 0.0
    codebase_coverage: dict[str, Any] = field(default_factory=dict)
    node_types_present: list[str] = field(default_factory=list)

    def summary_text(self) -> str:
        lines = [
            "═" * 60,
            "  ENTERPRISE KNOWLEDGE GRAPH REPORT",
            "═" * 60,
            f"  Total Nodes: {self.total_nodes}",
            f"  Total Relations: {self.total_relations}",
            f"  Build Time: {self.build_duration_ms:.0f}ms",
            "",
            "  Node Types:",
        ]
        for ntype in sorted(self.by_type.items(), key=lambda x: -x[1]):
            lines.append(f"    {ntype[0]}: {ntype[1]}")
        if self.top_connected_nodes:
            lines.append("")
            lines.append("  Most Connected Nodes:")
            for n in self.top_connected_nodes[:5]:
                lines.append(f"    {n['name']} ({n['type']}): {n['connections']} connections")
        if self.orphans:
            lines.append("")
            lines.append(f"  Orphan Nodes: {len(self.orphans)}")
        lines.append("═" * 60)
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_nodes": self.total_nodes,
            "total_relations": self.total_relations,
            "by_type": self.by_type,
            "by_source": self.by_source,
            "top_connected_nodes": self.top_connected_nodes[:20],
            "orphans": self.orphans[:20],
            "build_duration_ms": round(self.build_duration_ms, 1),
            "codebase_coverage": self.codebase_coverage,
            "node_types_present": self.node_types_present,
        }


# ── Enterprise Knowledge Graph ────────────────────────────────────────────


class EnterpriseKnowledgeGraph:
    """Unified enterprise knowledge graph connecting all business domains.

    Builds a graph from multiple data sources:
    - Codebase knowledge (via CodebaseKnowledgeGraph)
    - Incidents (from incident files)
    - Decisions (from decision memory)
    - Documentation (from docs/ directory)
    - ADRs (from docs/adr/)
    - Configuration (from config files)
    - Tests and test coverage

    Thread-safe. JSON-persisted.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._nodes: dict[str, KGNode] = {}
        self._relations: list[KGRelation] = []
        self._built = False
        self._report: EnterpriseKGReport | None = None
        self._project_root = Path(".").resolve()
        self._persist_path = Path("json/enterprise_kg.json")

    # ── Index Building ──────────────────────────────────────────────────

    def build(self, force: bool = False) -> EnterpriseKGReport:
        """Build the enterprise knowledge graph from all available sources.

        Args:
            force: If True, rebuild even if already built.

        Returns:
            EnterpriseKGReport with full analysis.
        """
        with self._lock:
            if self._built and not force:
                return self._report or EnterpriseKGReport()

            t0 = time.time()
            _log.info("[ENTERPRISE_KG] Building enterprise knowledge graph...")

            self._nodes.clear()
            self._relations.clear()

            # 1. Codebase data (modules, symbols, APIs)
            self._build_codebase_nodes()

            # 2. Documentation and ADRs
            self._build_documentation_nodes()

            # 3. Incident data
            self._build_incident_nodes()

            # 4. Decision data
            self._build_decision_nodes()

            # 5. Configuration data
            self._build_config_nodes()

            # 6. Test coverage mapping
            self._build_test_nodes()

            # 7. Business process nodes
            self._build_business_process_nodes()

            # 8. Infrastructure nodes
            self._build_infrastructure_nodes()

            # Build report
            self._report = self._generate_report()
            self._report.build_duration_ms = (time.time() - t0) * 1000
            self._built = True
            self._persist()

            _log.info(
                "[ENTERPRISE_KG] Built: %d nodes, %d relations, %.0fms",
                self._report.total_nodes,
                self._report.total_relations,
                self._report.build_duration_ms,
            )

            return self._report

    def reset(self) -> None:
        """Reset the graph (for testing)."""
        with self._lock:
            self._nodes.clear()
            self._relations.clear()
            self._built = False
            self._report = None

    # ── Query Methods ───────────────────────────────────────────────────

    def search(self, query: str, node_type: str = "") -> list[KGNode]:
        """Search for nodes matching the query."""
        query_lower = query.lower()
        results: list[KGNode] = []
        with self._lock:
            for node in self._nodes.values():
                if query_lower in node.name.lower() or any(
                    query_lower in str(v).lower()
                    for v in node.properties.values()
                ):
                    if not node_type or node.node_type == node_type:
                        results.append(node)
        return results

    def get_node(self, node_id: str) -> KGNode | None:
        """Get a specific node by ID."""
        with self._lock:
            return self._nodes.get(node_id)

    def get_relations(
        self, node_id: str, relation_type: str = ""
    ) -> list[KGRelation]:
        """Get all relations for a node."""
        results: list[KGRelation] = []
        with self._lock:
            for rel in self._relations:
                if rel.source_id == node_id or rel.target_id == node_id:
                    if not relation_type or rel.relation_type == relation_type:
                        results.append(rel)
        return results

    def get_connected_nodes(
        self, node_id: str, max_depth: int = 2
    ) -> list[dict[str, Any]]:
        """Get all nodes connected to a given node, up to max_depth hops."""
        connected: dict[str, int] = {}
        visited: set[str] = set()

        def dfs(current_id: str, current_depth: int) -> None:
            if current_depth > max_depth or current_id in visited:
                return
            visited.add(current_id)
            for rel in self._relations:
                if rel.source_id == current_id and rel.target_id not in visited:
                    next_depth = current_depth + 1
                    if next_depth <= max_depth:
                        connected[rel.target_id] = next_depth
                        dfs(rel.target_id, next_depth)
                elif rel.target_id == current_id and rel.source_id not in visited:
                    next_depth = current_depth + 1
                    if next_depth <= max_depth:
                        connected[rel.source_id] = next_depth
                        dfs(rel.source_id, next_depth)

        dfs(node_id, 0)
        return [
            {
                "node_id": nid,
                "name": self._nodes[nid].name if nid in self._nodes else nid,
                "type": self._nodes[nid].node_type if nid in self._nodes else "UNKNOWN",
                "distance": dist,
            }
            for nid, dist in sorted(connected.items(), key=lambda x: x[1])
        ]

    def get_report(self) -> EnterpriseKGReport:
        """Get the full enterprise knowledge graph report.

        Returns cached report if built, otherwise generates from current state.
        """
        with self._lock:
            if self._report is not None:
                return self._report
            return self._generate_report()

    def get_stats(self) -> dict[str, Any]:
        """Get quick statistics."""
        with self._lock:
            return {
                "total_nodes": len(self._nodes),
                "total_relations": len(self._relations),
                "by_type": {
                    ntype: sum(
                        1 for n in self._nodes.values()
                        if n.node_type == ntype
                    )
                    for ntype in NODE_TYPES
                },
                "built": self._built,
            }

    # ── Build Methods ───────────────────────────────────────────────────

    def _add_node(self, node: KGNode) -> None:
        """Add a node, deduplicating by ID."""
        if node.node_id in self._nodes:
            existing = self._nodes[node.node_id]
            existing.weight = max(existing.weight, node.weight)
            existing.properties.update(node.properties)
        else:
            self._nodes[node.node_id] = node

    def _add_relation(self, relation: KGRelation) -> None:
        """Add a relation."""
        # Deduplicate
        for existing in self._relations:
            if (existing.source_id == relation.source_id
                    and existing.target_id == relation.target_id
                    and existing.relation_type == relation.relation_type):
                existing.weight = max(existing.weight, relation.weight)
                return
        self._relations.append(relation)

    def _build_codebase_nodes(self) -> None:
        """Add nodes and relations from the codebase."""
        try:
            from core.codebase_knowledge_graph import get_knowledge_graph

            kg = get_knowledge_graph()
            kg.build_index()

            # Add module nodes
            for mod_path, mod_info in kg._modules.items():
                short_name = mod_path.split("/")[-1].replace(".py", "")
                self._add_node(KGNode(
                    node_id=f"module:{mod_path}",
                    name=short_name,
                    node_type="MODULE",
                    properties={
                        "path": mod_path,
                        "lines": mod_info.lines,
                        "symbols": len(mod_info.symbols),
                        "imports": len(mod_info.imports),
                        "has_tests": mod_info.has_tests,
                    },
                    source="codebase",
                    weight=min(1.0, mod_info.lines / 1000),
                ))

                # Add symbol nodes and relations
                for sym in mod_info.symbols:
                    sym_id = f"symbol:{mod_path}:{sym.name}"
                    self._add_node(KGNode(
                        node_id=sym_id,
                        name=sym.name,
                        node_type="SYMBOL",
                        properties={
                            "type": sym.symbol_type,
                            "module": mod_path,
                            "line": sym.line,
                            "complexity": sym.complexity,
                        },
                        source="codebase",
                        weight=min(1.0, sym.complexity / 20),
                    ))
                    self._add_relation(KGRelation(
                        source_id=f"module:{mod_path}",
                        target_id=sym_id,
                        relation_type="CONTAINS",
                    ))

                # Add dependency relations between modules
                for dep in mod_info.imports[:10]:
                    dep_id = f"module:{dep.replace('.', '/')}.py"
                    self._add_relation(KGRelation(
                        source_id=f"module:{mod_path}",
                        target_id=dep_id,
                        relation_type="DEPENDS_ON",
                    ))

        except ImportError:
            _log.debug("[ENTERPRISE_KG] CodebaseKnowledgeGraph not available")

    def _build_documentation_nodes(self) -> None:
        """Add nodes from documentation files."""
        docs_dir = self._project_root / "docs"
        if not docs_dir.is_dir():
            return

        for md_file in docs_dir.rglob("*.md"):
            rel_path = str(md_file.relative_to(self._project_root))
            name = md_file.stem.replace("_", " ").replace("-", " ").title()

            # Determine if it's an ADR
            is_adr = "adr" in rel_path.lower()
            node_type = "ADR" if is_adr else "DOCUMENT"

            # Count words as a rough size metric
            try:
                content = md_file.read_text(encoding="utf-8", errors="ignore")
                word_count = len(content.split())
            except OSError:
                word_count = 0

            self._add_node(KGNode(
                node_id=f"doc:{rel_path}",
                name=name,
                node_type=node_type,
                properties={
                    "path": rel_path,
                    "words": word_count,
                    "is_adr": is_adr,
                },
                source="documentation",
                weight=min(1.0, word_count / 1000),
            ))

            # Link ADRs to modules mentioned in them
            if is_adr and word_count > 0:
                try:
                    for mod_match in re.finditer(
                        r"core/[a-z_]+(?:/[a-z_]+)*\.py", content
                    ):
                        mod_path = mod_match.group()
                        self._add_relation(KGRelation(
                            source_id=f"doc:{rel_path}",
                            target_id=f"module:{mod_path}",
                            relation_type="REFERENCES",
                        ))
                except (re.error, ValueError):
                    pass

    def _build_incident_nodes(self) -> None:
        """Add nodes from incident data."""
        # Try to load incident history
        incident_paths = [
            self._project_root / "data" / "json/incidents.json",
            self._project_root / "json/incidents.json",
        ]

        for path in incident_paths:
            if path.is_file():
                try:
                    incidents = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(incidents, list):
                        for incident in incidents[:200]:
                            inc_id = incident.get("incident_id", str(id(incident)))
                            title = incident.get("title", "Unknown Incident")
                            severity = incident.get("severity", "MEDIUM")

                            self._add_node(KGNode(
                                node_id=f"incident:{inc_id}",
                                name=title[:80],
                                node_type="INCIDENT",
                                properties={
                                    "severity": severity,
                                    "source": incident.get("source", ""),
                                    "status": incident.get("status", ""),
                                },
                                source="incident",
                                weight={
                                    "CRITICAL": 1.0,
                                    "HIGH": 0.8,
                                    "MEDIUM": 0.5,
                                    "LOW": 0.3,
                                }.get(severity.upper(), 0.5),
                            ))

                            # Link to affected modules
                            affected = incident.get("affected_modules", [])
                            if isinstance(affected, list):
                                for mod in affected:
                                    self._add_relation(KGRelation(
                                        source_id=f"incident:{inc_id}",
                                        target_id=f"module:{mod}",
                                        relation_type="AFFECTS",
                                    ))
                except (json.JSONDecodeError, OSError, ValueError) as exc:
                    _log.debug("[ENTERPRISE_KG] Incident load error: %s", exc)

    def _build_decision_nodes(self) -> None:
        """Add nodes from decision memory."""
        try:
            from core.decision_memory import get_decision_memory

            memory = get_decision_memory()
            report = memory.get_report()

            for decision in report.recent_decisions:
                dec_id = decision.decision_id
                self._add_node(KGNode(
                    node_id=f"decision:{dec_id}",
                    name=decision.title[:80],
                    node_type="DECISION",
                    properties={
                        "status": decision.status,
                        "priority": decision.priority,
                        "impact": ", ".join(decision.impact_categories),
                        "author": decision.author,
                    },
                    source="decision",
                    weight={
                        "CRITICAL": 1.0,
                        "HIGH": 0.8,
                        "MEDIUM": 0.5,
                        "LOW": 0.3,
                    }.get(decision.priority.upper(), 0.5),
                ))

                # Link to affected modules
                for mod_path in decision.module_paths:
                    self._add_relation(KGRelation(
                        source_id=f"decision:{dec_id}",
                        target_id=f"module:{mod_path}",
                        relation_type="AFFECTS",
                    ))

        except ImportError:
            _log.debug("[ENTERPRISE_KG] DecisionMemory not available")

    def _build_config_nodes(self) -> None:
        """Add nodes from configuration files."""
        config_files = [
            "json/config.json",
            "json/stock_config.json",
            "json/index_config.defaults.json",
            "json/dashboard_config.json",
            "json/config.template.json",
        ]

        for config_file in config_files:
            path = self._project_root / config_file
            if path.is_file():
                try:
                    content = path.read_text(encoding="utf-8")
                    config = json.loads(content)
                    keys = list(config.keys()) if isinstance(config, dict) else []

                    self._add_node(KGNode(
                        node_id=f"config:{config_file}",
                        name=config_file,
                        node_type="CONFIG",
                        properties={
                            "path": config_file,
                            "keys": len(keys),
                            "sample_keys": ",".join(keys[:10]),
                        },
                        source="config",
                        weight=0.5,
                    ))

                    # Link config to modules that reference it
                    for key in keys[:20]:
                        clean_key = key.lower().replace("_", " ").replace("-", " ")
                        # Try to find a matching module
                        for node_id in self._nodes:
                            if "/" in node_id:
                                mod_name = node_id.split("/")[-1].replace(".py", "")
                                if any(
                                    word in mod_name.lower()
                                    for word in clean_key.split()
                                    if len(word) > 3
                                ):
                                    self._add_relation(KGRelation(
                                        source_id=f"config:{config_file}",
                                        target_id=node_id,
                                        relation_type="CONFIGURES",
                                    ))

                except (json.JSONDecodeError, OSError) as exc:
                    _log.debug(
                        "[ENTERPRISE_KG] Config load error for %s: %s",
                        config_file, exc,
                    )

    def _build_test_nodes(self) -> None:
        """Add nodes from test files and map to modules."""
        tests_dir = self._project_root / "tests"
        if not tests_dir.is_dir():
            return

        for test_file in tests_dir.glob("test_*.py"):
            rel_path = str(test_file.relative_to(self._project_root))
            name = test_file.stem.replace("test_", "").replace("_", " ").title()

            self._add_node(KGNode(
                node_id=f"test:{rel_path}",
                name=name,
                node_type="TEST",
                properties={
                    "path": rel_path,
                    "size": test_file.stat().st_size,
                },
                source="test",
                weight=0.4,
            ))

            # Link test to module it tests
            # Convention: test_<module>.py tests core/<module>.py
            tested_module = f"core/{test_file.stem.replace('test_', '')}.py"
            if (self._project_root / tested_module).is_file():
                self._add_relation(KGRelation(
                    source_id=f"test:{rel_path}",
                    target_id=f"module:{tested_module}",
                    relation_type="TESTS",
                ))

    def _build_business_process_nodes(self) -> None:
        """Add business process and workflow nodes."""
        workflows = {
            "signal_generation": {
                "name": "Signal Generation Pipeline",
                "steps": [
                    "market_data", "signal_scoring", "ml_inference",
                    "tier_classification", "approval",
                ],
            },
            "trade_execution": {
                "name": "Trade Execution Workflow",
                "steps": [
                    "position_sizing", "order_submission",
                    "fill_tracking", "risk_monitoring",
                ],
            },
            "risk_management": {
                "name": "Risk Management Process",
                "steps": [
                    "circuit_breaker", "loss_limit", "position_monitor",
                    "var_calculation", "stress_testing",
                ],
            },
            "compliance": {
                "name": "Compliance & Audit Process",
                "steps": [
                    "constitution_checks", "audit_logging",
                    "governance_review", "report_generation",
                ],
            },
            "incident_response": {
                "name": "Incident Response Process",
                "steps": [
                    "detection", "analysis", "healing",
                    "postmortem", "prevention",
                ],
            },
        }

        for bp_id, bp_data in workflows.items():
            self._add_node(KGNode(
                node_id=f"process:{bp_id}",
                name=bp_data["name"],
                node_type="BUSINESS_PROCESS",
                properties={
                    "steps": ", ".join(bp_data["steps"]),
                    "n_steps": len(bp_data["steps"]),
                },
                source="definition",
                weight=0.7,
            ))

            # Link process steps to modules
            for step in bp_data["steps"]:
                for node_id in self._nodes:
                    if step.lower() in node_id.lower():
                        self._add_relation(KGRelation(
                            source_id=f"process:{bp_id}",
                            target_id=node_id,
                            relation_type="IMPLEMENTS",
                        ))

    def _build_infrastructure_nodes(self) -> None:
        """Add infrastructure and deployment nodes."""
        infra_items = {
            "database_sqlite": {"name": "SQLite Database", "type": "DATABASE"},
            "database_postgres": {"name": "PostgreSQL Adapter", "type": "DATABASE"},
            "web_dashboard": {"name": "Enterprise Dashboard", "type": "DEPLOYMENT"},
            "docker_setup": {"name": "Docker Deployment", "type": "DEPLOYMENT"},
            "ci_pipeline": {"name": "CI/CD Pipeline", "type": "DEPLOYMENT"},
        }

        for infra_id, infra_data in infra_items.items():
            self._add_node(KGNode(
                node_id=f"infra:{infra_id}",
                name=infra_data["name"],
                node_type=infra_data["type"],
                source="infrastructure",
                weight=0.6,
            ))

    # ── Report Generation ──────────────────────────────────────────────

    def _generate_report(self) -> EnterpriseKGReport:
        """Generate the enterprise knowledge graph report."""
        report = EnterpriseKGReport()
        report.total_nodes = len(self._nodes)
        report.total_relations = len(self._relations)

        # By type
        by_type: dict[str, int] = {}
        for node in self._nodes.values():
            by_type[node.node_type] = by_type.get(node.node_type, 0) + 1
        report.by_type = by_type

        # By source
        by_source: dict[str, int] = {}
        for node in self._nodes.values():
            by_source[node.source] = by_source.get(node.source, 0) + 1
        report.by_source = by_source

        # Node types present
        report.node_types_present = [
            nt for nt in NODE_TYPES if nt in by_type
        ]

        # Most connected nodes
        connection_counts: dict[str, int] = {}
        for rel in self._relations:
            connection_counts[rel.source_id] = (
                connection_counts.get(rel.source_id, 0) + 1
            )
            connection_counts[rel.target_id] = (
                connection_counts.get(rel.target_id, 0) + 1
            )

        sorted_nodes = sorted(
            [
                {
                    "node_id": nid,
                    "name": self._nodes[nid].name if nid in self._nodes else nid,
                    "type": self._nodes[nid].node_type if nid in self._nodes else "UNKNOWN",
                    "connections": count,
                }
                for nid, count in connection_counts.items()
            ],
            key=lambda x: -x["connections"],
        )
        report.top_connected_nodes = sorted_nodes[:20]

        # Orphans (nodes with no relations)
        connected_ids = set()
        for rel in self._relations:
            connected_ids.add(rel.source_id)
            connected_ids.add(rel.target_id)
        report.orphans = [
            n.name for nid, n in self._nodes.items()
            if nid not in connected_ids
        ][:50]

        # Codebase coverage stats
        module_count = by_type.get("MODULE", 0)
        test_count = by_type.get("TEST", 0)
        doc_count = by_type.get("DOCUMENT", 0) + by_type.get("ADR", 0)
        report.codebase_coverage = {
            "modules_mapped": module_count,
            "tests_mapped": test_count,
            "documents_mapped": doc_count,
            "decisions_mapped": by_type.get("DECISION", 0),
            "incidents_mapped": by_type.get("INCIDENT", 0),
            "processes_mapped": by_type.get("BUSINESS_PROCESS", 0),
        }

        return report

    # ── Persistence ────────────────────────────────────────────────────

    def _persist(self) -> None:
        """Persist the enterprise KG to JSON."""
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "nodes": [n.to_dict() for n in self._nodes.values()],
                "relations": [r.to_dict() for r in self._relations],
            }
            self._persist_path.write_text(
                json.dumps(data, indent=2), encoding="utf-8"
            )
        except (OSError, ValueError) as exc:
            _log.debug("[ENTERPRISE_KG] Persist error: %s", exc)

    def load(self) -> bool:
        """Load previously persisted KG from disk.

        Returns:
            True if loaded successfully, False otherwise.
        """
        try:
            if self._persist_path.is_file():
                data = json.loads(
                    self._persist_path.read_text(encoding="utf-8")
                )
                for ndata in data.get("nodes", []):
                    node = KGNode(
                        node_id=ndata.get("node_id", ""),
                        name=ndata.get("name", ""),
                        node_type=ndata.get("type", "UNKNOWN"),
                        properties=ndata.get("properties", {}),
                        source=ndata.get("source", ""),
                        weight=ndata.get("weight", 1.0),
                    )
                    self._nodes[node.node_id] = node
                for rdata in data.get("relations", []):
                    rel = KGRelation(
                        source_id=rdata.get("source", ""),
                        target_id=rdata.get("target", ""),
                        relation_type=rdata.get("type", ""),
                        properties=rdata.get("properties", {}),
                        weight=rdata.get("weight", 1.0),
                    )
                    self._relations.append(rel)
                self._built = True
                _log.info(
                    "[ENTERPRISE_KG] Loaded: %d nodes, %d relations",
                    len(self._nodes), len(self._relations),
                )
                return True
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
            _log.debug("[ENTERPRISE_KG] Load error: %s", exc)
        return False


# ── Singleton ──────────────────────────────────────────────────────────────

_instance: EnterpriseKnowledgeGraph | None = None
_instance_lock = threading.RLock()


def get_enterprise_knowledge_graph() -> EnterpriseKnowledgeGraph:
    """Get the singleton EnterpriseKnowledgeGraph instance."""
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = EnterpriseKnowledgeGraph()
        return _instance


def reset_enterprise_knowledge_graph() -> None:
    """Force-reset singleton (for testing)."""
    global _instance
    with _instance_lock:
        _instance = None


__all__ = [
    "EnterpriseKnowledgeGraph",
    "EnterpriseKGReport",
    "KGNode",
    "KGRelation",
    "get_enterprise_knowledge_graph",
    "reset_enterprise_knowledge_graph",
]
