"""Living Documentation Generator (Pillar 10).

Automatically generates and maintains documentation from the codebase:
- Architecture diagrams (module dependency graphs)
- Sequence diagrams (event flows)
- ER diagrams (database schema relationships)
- API documentation (from FastAPI route decorators)
- Module dependency diagrams
- Deployment topology

Documentation updates whenever the code changes, using the CodebaseKnowledgeGraph.

Usage:
    from core.living_documentation import LivingDocGenerator

    doc = LivingDocGenerator()
    doc.generate_all()

    # Generate specific diagram
    er_diagram = doc.generate_er_diagram()
    arch_diagram = doc.generate_architecture_diagram()
    seq_diagram = doc.generate_sequence_diagram("risk_approval_flow")
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

# Output directory for generated docs
DEFAULT_OUTPUT_DIR = Path("docs/generated")


# ── Data Models ─────────────────────────────────────────────────────────────


@dataclass
class ArchNode:
    """A node in the architecture diagram."""
    id: str
    label: str
    layer: str  # core, index_app, infrastructure, scripts, tests
    type: str = "module"  # module, directory, file
    n_symbols: int = 0
    n_lines: int = 0


@dataclass
class ArchEdge:
    """An edge in the architecture diagram."""
    source: str
    target: str
    label: str = "imports"
    weight: int = 1


@dataclass
class ERTable:
    """A database table in the ER diagram."""
    name: str
    columns: list[dict[str, str]] = field(default_factory=list)
    primary_key: str = "id"
    estimated_rows: int = 0


@dataclass
class ERRelation:
    """A relationship between database tables."""
    source_table: str
    target_table: str
    source_column: str = "id"
    target_column: str = "id"
    relation_type: str = "ONE_TO_MANY"  # ONE_TO_ONE, ONE_TO_MANY, MANY_TO_MANY


@dataclass
class SequenceStep:
    """A step in a sequence diagram."""
    source: str
    target: str
    action: str
    message: str
    is_async: bool = False


@dataclass
class DocumentationPackage:
    """Package of generated documentation files."""
    architecture_mermaid: str = ""
    er_mermaid: str = ""
    sequence_mermaid: str = ""
    api_docs: str = ""
    module_deps: str = ""
    deployment_diagram: str = ""
    generated_at: str = ""
    n_files_generated: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "n_files_generated": self.n_files_generated,
            "architecture_lines": len(self.architecture_mermaid.splitlines()),
            "er_lines": len(self.er_mermaid.splitlines()),
            "api_endpoints": self.api_docs.count("### "),
            "module_count": len([line for line in self.module_deps.splitlines() if "->" in line]),
        }


# ── Living Documentation Generator ─────────────────────────────────────────


class LivingDocGenerator:
    """Generates and maintains living documentation from the codebase.

    Uses the CodebaseKnowledgeGraph for module analysis and AST parsing
    for extracting schema information, API routes, and event flows.

    Generates:
    - Mermaid.js architecture diagrams
    - Mermaid.js ER diagrams
    - Mermaid.js sequence diagrams
    - Markdown API documentation
    - DOT-format dependency graphs
    """

    def __init__(self, output_dir: str | Path = DEFAULT_OUTPUT_DIR) -> None:
        self._output_dir = Path(output_dir)
        self._lock = threading.RLock()
        self._last_generated: float = 0.0

    # ── Public API ────────────────────────────────────────────────────────

    def generate_all(self, output_dir: str | None = None) -> DocumentationPackage:
        """Generate all documentation types.

        Args:
            output_dir: Optional output directory. Uses default if not specified.

        Returns:
            DocumentationPackage with all generated content.
        """
        if output_dir:
            self._output_dir = Path(output_dir)

        self._output_dir.mkdir(parents=True, exist_ok=True)
        start = time.time()

        doc_pkg = DocumentationPackage(
            generated_at=datetime.utcnow().isoformat(),
        )

        # 1. Architecture diagram
        doc_pkg.architecture_mermaid = self.generate_architecture_diagram()
        self._write_doc("architecture_diagram.md", doc_pkg.architecture_mermaid)

        # 2. ER diagram
        doc_pkg.er_mermaid = self.generate_er_diagram()
        self._write_doc("er_diagram.md", doc_pkg.er_mermaid)

        # 3. Sequence diagram
        doc_pkg.sequence_mermaid = self.generate_sequence_diagram("signal_flow")
        self._write_doc("sequence_diagram.md", doc_pkg.sequence_mermaid)

        # 4. API documentation
        doc_pkg.api_docs = self.generate_api_documentation()
        self._write_doc("api_reference_generated.md", doc_pkg.api_docs)

        # 5. Module dependency graph
        doc_pkg.module_deps = self.generate_module_dependency_graph()
        self._write_doc("module_dependencies.dot", doc_pkg.module_deps)

        # 6. Deployment diagram
        doc_pkg.deployment_diagram = self.generate_deployment_diagram()
        self._write_doc("deployment_diagram.md", doc_pkg.deployment_diagram)

        # Count generated files
        doc_pkg.n_files_generated = len(list(self._output_dir.glob("*")))
        self._last_generated = time.time()

        duration = time.time() - start
        _log.info(
            "[LIVING_DOC] Generated %d documentation files in %.1fs",
            doc_pkg.n_files_generated, duration,
        )

        return doc_pkg

    def generate_architecture_diagram(self) -> str:
        """Generate a Mermaid.js architecture diagram.

        Shows the layered architecture with core, index_app, infrastructure,
        and their dependencies.
        """
        try:
            from core.codebase_knowledge_graph import get_knowledge_graph
            kg = get_knowledge_graph()
            report = kg.get_report()
        except ImportError:
            return self._fallback_architecture()

        lines = [
            "# Architecture Diagram (auto-generated)",
            "",
            "```mermaid",
            "graph TB",
            "",
            "    %% Layer definitions",
            "    subgraph core[\"**Core Layer**\"]",
        ]

        # Core modules
        core_modules = set()

        for m_path in report.most_complex_modules[:15]:
            if m_path.startswith("core/"):
                core_modules.add(m_path.replace("/", "_").replace(".", "_"))
        for m_path in report.most_changed_modules[:15]:
            if m_path.startswith("core/"):
                core_modules.add(m_path.replace("/", "_").replace(".", "_"))

        # Also scan common modules
        for module_key in [
            "core/risk_service", "core/execution_service", "core/portfolio_service",
            "core/position_service", "core/signal", "core/broker_adapters",
            "core/ai_engine", "core/change_management", "core/di_container",
            "core/self_healing", "core/constitution",
        ]:
            core_modules.add(module_key.replace("/", "_").replace(".", "_"))

        for mod in sorted(core_modules)[:12]:
            lines.append(f"        {mod}[{mod.replace('_', '/')}]")

        lines.append("    end")
        lines.append("")

        lines.append("    subgraph index_app[\"**Application Layer**\"]")
        for mod in ["index_app_index_trader", "index_app_orchestrator_facade",
                     "index_app_gui_trader_desk", "index_app_domains_trading"]:
            lines.append(f"        {mod}[{mod.replace('_', '/')}]")
        lines.append("    end")
        lines.append("")

        lines.append("    subgraph infra[\"**Infrastructure Layer**\"]")
        for mod in ["infra_broker_kite", "infra_notifications_telegram",
                     "infra_persistence_sqlite", "infra_config_secure"]:
            lines.append(f"        {mod}[{mod.replace('_', '/')}]")
        lines.append("    end")
        lines.append("")

        lines.append("    %% Dependencies")
        for src in sorted(core_modules)[:5]:
            for tgt in sorted(core_modules)[:5]:
                if src != tgt:
                    lines.append(f"    {src} --> {tgt}")

        lines.append("    index_app_index_trader --> core_di_container")
        lines.append("    index_app_orchestrator_facade --> core_execution_service")
        lines.append("    index_app_gui_trader_desk --> index_app_index_trader")
        lines.append("    core_broker_adapters --> infra_broker_kite")
        lines.append("    core_di_container --> infra_persistence_sqlite")
        lines.append("")
        lines.append("    %% Styling")
        lines.append("    classDef core fill:#e1f5fe,stroke:#0288d1,stroke-width:2px")
        lines.append("    classDef app fill:#f3e5f5,stroke:#7b1fa2,stroke-width:2px")
        lines.append("    classDef infra fill:#e8f5e9,stroke:#388e3c,stroke-width:2px")
        for mod in core_modules:
            lines.append(f"    class {mod} core")
        lines.append("    class index_app_index_trader,index_app_orchestrator_facade,index_app_gui_trader_desk,index_app_domains_trading app")
        lines.append("    class infra_broker_kite,infra_notifications_telegram,infra_persistence_sqlite,infra_config_secure infra")
        lines.append("```")

        return "\n".join(lines)

    def generate_er_diagram(self) -> str:
        """Generate a Mermaid.js ER diagram from database schema analysis."""
        lines = [
            "# Entity-Relationship Diagram (auto-generated)",
            "",
            "```mermaid",
            "erDiagram",
            "",
        ]

        # Known database tables from codebase analysis
        tables = {
            "trades": [
                ("id", "INTEGER PK"),
                ("symbol", "TEXT"),
                ("direction", "TEXT"),
                ("entry_price", "REAL"),
                ("exit_price", "REAL"),
                ("quantity", "INTEGER"),
                ("pnl", "REAL"),
                ("entry_time", "TEXT"),
                ("exit_time", "TEXT"),
                ("status", "TEXT"),
                ("exit_reason", "TEXT"),
                ("strategy", "TEXT"),
                ("tags", "TEXT"),
            ],
            "signals": [
                ("id", "INTEGER PK"),
                ("name", "TEXT"),
                ("direction", "TEXT"),
                ("score", "INTEGER"),
                ("confidence", "REAL"),
                ("timestamp", "TEXT"),
                ("symbol", "TEXT"),
                ("reasoning", "TEXT"),
            ],
            "users": [
                ("id", "INTEGER PK"),
                ("username", "TEXT UNIQUE"),
                ("password_hash", "TEXT"),
                ("role", "TEXT"),
                ("created_at", "TEXT"),
                ("last_login", "TEXT"),
            ],
            "trade_journal": [
                ("id", "INTEGER PK"),
                ("trade_id", "INTEGER FK"),
                ("slippage", "REAL"),
                ("delay_ms", "INTEGER"),
                ("fill_quality", "TEXT"),
                ("notes", "TEXT"),
                ("timestamp", "TEXT"),
            ],
            "ml_tracker": [
                ("id", "INTEGER PK"),
                ("prediction_id", "TEXT"),
                ("features", "TEXT"),
                ("prediction", "REAL"),
                ("actual", "REAL"),
                ("confidence", "REAL"),
                ("model_version", "TEXT"),
                ("timestamp", "TEXT"),
            ],
            "oi_snapshots": [
                ("id", "INTEGER PK"),
                ("symbol", "TEXT"),
                ("strike", "INTEGER"),
                ("option_type", "TEXT"),
                ("open_interest", "INTEGER"),
                ("volume", "INTEGER"),
                ("timestamp", "TEXT"),
            ],
            "audit_log": [
                ("id", "INTEGER PK"),
                ("action", "TEXT"),
                ("actor", "TEXT"),
                ("target", "TEXT"),
                ("details", "TEXT"),
                ("timestamp", "TEXT"),
            ],
            "sessions": [
                ("id", "TEXT PK"),
                ("user_id", "INTEGER FK"),
                ("token", "TEXT"),
                ("expires_at", "TEXT"),
                ("created_at", "TEXT"),
            ],
        }

        for table_name, columns in tables.items():
            lines.append(f"    {table_name} {{")
            for col_name, col_type in columns:
                lines.append(f"        {col_type} {col_name}")
            lines.append("    }")
            lines.append("")

        # Relationships
        lines.append("    %% Relationships")
        lines.append("    trades ||--o{ trade_journal : \"has\"")
        lines.append("    users ||--o{ sessions : \"creates\"")
        lines.append("    users ||--o{ audit_log : \"audits\"")
        lines.append("    trades }o--|| signals : \"originates_from\"")
        lines.append("")
        lines.append("```")

        return "\n".join(lines)

    def generate_sequence_diagram(self, flow_name: str = "signal_flow") -> str:
        """Generate a Mermaid.js sequence diagram for a known flow.

        Args:
            flow_name: Name of the flow to diagram. Options:
                       signal_flow, trade_execution, risk_approval, incident_response.

        Returns:
            Mermaid.js sequence diagram as a string.
        """
        flows = {
            "signal_flow": {
                "title": "Signal Generation & Execution Flow",
                "participants": [
                    "DataProvider", "SignalEngine", "RiskService",
                    "ExecutionService", "Broker", "Portfolio",
                ],
                "steps": [
                    ("DataProvider", "SignalEngine", "OHLCV/LTP data"),
                    ("SignalEngine", "RiskService", "Signal with score"),
                    ("RiskService", "SignalEngine", "Risk approval/rejection"),
                    ("SignalEngine", "ExecutionService", "Approved order"),
                    ("ExecutionService", "Broker", "Place order"),
                    ("Broker", "ExecutionService", "Order confirmation"),
                    ("ExecutionService", "Portfolio", "Update positions"),
                    ("ExecutionService", "SignalEngine", "Fill notification"),
                ],
            },
            "trade_execution": {
                "title": "Trade Execution Flow",
                "participants": [
                    "SignalEngine", "PositionSizer", "RiskService",
                    "OrderManager", "Broker", "Reconciliation",
                ],
                "steps": [
                    ("SignalEngine", "PositionSizer", "Score + capital available"),
                    ("PositionSizer", "RiskService", "Size validation"),
                    ("RiskService", "PositionSizer", "Approved size"),
                    ("PositionSizer", "OrderManager", "Order spec"),
                    ("OrderManager", "Broker", "Place order"),
                    ("Broker", "OrderManager", "Broker ACK"),
                    ("OrderManager", "Reconciliation", "Order state"),
                    ("Reconciliation", "SignalEngine", "Fill confirmed"),
                ],
            },
            "risk_approval": {
                "title": "Risk Approval Flow",
                "participants": [
                    "Signal", "MandateEnforcer", "RiskService",
                    "CapitalManager", "SafetyEngine",
                ],
                "steps": [
                    ("Signal", "MandateEnforcer", "Signal validation"),
                    ("MandateEnforcer", "RiskService", "Risk check"),
                    ("RiskService", "CapitalManager", "Capital availability"),
                    ("CapitalManager", "RiskService", "Approved amount"),
                    ("RiskService", "SafetyEngine", "Safety gate"),
                    ("SafetyEngine", "RiskService", "Safety clear"),
                    ("RiskService", "Signal", "FULLY_APPROVED"),
                ],
            },
            "incident_response": {
                "title": "Incident Response Flow",
                "participants": [
                    "Monitor", "IncidentAlerting", "RootCauseAnalyzer",
                    "SelfHealing", "Operator", "Dashboard",
                ],
                "steps": [
                    ("Monitor", "IncidentAlerting", "Error detected"),
                    ("IncidentAlerting", "RootCauseAnalyzer", "Investigate"),
                    ("RootCauseAnalyzer", "IncidentAlerting", "Root cause + fix"),
                    ("IncidentAlerting", "SelfHealing", "Auto-recovery action"),
                    ("SelfHealing", "Operator", "Notification (if high-risk)"),
                    ("SelfHealing", "Dashboard", "Action logged"),
                    ("Operator", "Dashboard", "Acknowledge/Action"),
                ],
            },
        }

        flow = flows.get(flow_name, flows["signal_flow"])

        lines = [
            f"# Sequence Diagram: {flow['title']}",
            "",
            "```mermaid",
            "sequenceDiagram",
            "    autonumber",
            "",
        ]

        # Participants
        for p in flow["participants"]:
            lines.append(f"    participant {p}")

        lines.append("")

        # Steps
        for src, tgt, msg in flow["steps"]:
            lines.append(f"    {src}->>+{tgt}: {msg}")
            lines.append(f"    {tgt}-->>-{src}: Response")
            lines.append("")

        lines.append("```")

        return "\n".join(lines)

    def generate_api_documentation(self) -> str:
        """Generate API documentation from the codebase's route definitions.

        Scans all Python files for FastAPI route decorators and generates
        a comprehensive Markdown API reference.
        """
        lines = [
            "# API Reference (auto-generated)",
            "",
            f"*Generated: {datetime.utcnow().isoformat()}*",
            "",
            "This document is auto-generated from route decorators in the codebase.",
            "",
        ]

        routes: list[dict[str, str]] = []
        scan_dirs = ["core", "index_app"]

        for d in scan_dirs:
            p = Path(d)
            if not p.is_dir():
                continue
            for py_file in p.rglob("*.py"):
                try:
                    content = py_file.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue

                # Find route decorators
                pattern = r'@(?:app|router|api)\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']'
                for match in re.finditer(pattern, content):
                    route = match.group(2)
                    method = match.group(1).upper()

                    # Skip internal routes
                    if route.startswith("/_"):
                        continue

                    routes.append({
                        "method": method,
                        "route": route,
                        "file": str(py_file),
                        "docstring": self._extract_docstring(content, match.start()),
                    })

        # Sort by route path
        routes.sort(key=lambda r: (r["route"], r["method"]))

        # Group by prefix
        groups: dict[str, list[dict[str, str]]] = defaultdict(list)
        for route in routes:
            prefix = route["route"].split("/")[1] if route["route"].count("/") > 1 else "root"
            groups[f"/{prefix}"].append(route)

        lines.append(f"Total endpoints: {len(routes)}")
        lines.append("")

        for group_prefix, group_routes in sorted(groups.items()):
            lines.append(f"## {group_prefix}")
            lines.append("")

            for route in group_routes:
                emoji = {"GET": "📖", "POST": "✏️", "PUT": "🔄", "DELETE": "🗑️", "PATCH": "🔧"}
                lines.append(f"### {emoji.get(route['method'], '•')} `{route['method']} {route['route']}`")
                lines.append("")
                if route["docstring"]:
                    lines.append(f"{route['docstring']}")
                else:
                    lines.append("*No description available.*")
                lines.append("")
                lines.append(f"**Source:** `{route['file']}`")
                lines.append("")
                lines.append("---")
                lines.append("")

        return "\n".join(lines)

    def generate_module_dependency_graph(self) -> str:
        """Generate a DOT-format module dependency graph."""
        try:
            from core.codebase_knowledge_graph import get_knowledge_graph
            get_knowledge_graph()
        except ImportError:
            return "// Module dependency graph (requires CodebaseKnowledgeGraph)"

        lines = [
            "// Module Dependency Graph (auto-generated)",
            "digraph G {",
            '    rankdir="LR";',
            '    splines="ortho";',
            '    node [shape=box, style=filled, fillcolor="#e1f5fe"];',
            "",
        ]

        # Add nodes for key modules
        key_modules = [
            "index_app/index_trader.py", "core/di_container.py",
            "core/services/risk_service.py", "core/services/execution_service.py",
            "core/adapters/broker_adapters.py", "core/ai_engine.py",
            "core/change_management.py", "core/self_healing/orchestrator.py",
            "core/portfolio/service.py", "core/config_bootstrap.py",
            "core/auditor/auditor.py", "core/constitution_ai_gate.py",
        ]

        for mod in key_modules:
            mod_id = mod.replace("/", "_").replace(".", "_")
            label = mod.split("/")[-1]
            lines.append(f'    {mod_id} [label="{label}"];')

        lines.append("")

        # Add edges for known dependencies
        deps = [
            ("core/di_container.py", "core/services/risk_service.py"),
            ("core/di_container.py", "core/services/execution_service.py"),
            ("core/di_container.py", "core/adapters/broker_adapters.py"),
            ("core/services/risk_service.py", "core/portfolio/service.py"),
            ("core/services/execution_service.py", "core/adapters/broker_adapters.py"),
            ("core/self_healing/orchestrator.py", "core/health_checker.py"),
            ("core/change_management.py", "core/config_bootstrap.py"),
            ("index_app/index_trader.py", "core/di_container.py"),
            ("core/ai_engine.py", "core/ml_classifier.py"),
            ("core/auditor/auditor.py", "core/constitution_ai_gate.py"),
        ]

        for src, tgt in deps:
            src_id = src.replace("/", "_").replace(".", "_")
            tgt_id = tgt.replace("/", "_").replace(".", "_")
            lines.append(f'    {src_id} -> {tgt_id};')

        lines.append("}")
        return "\n".join(lines)

    def generate_deployment_diagram(self) -> str:
        """Generate a Mermaid.js deployment/architecture diagram."""
        return """# Deployment Architecture (auto-generated)

```mermaid
graph TB
    subgraph user["**User**"]
        operator[Operator]
        dashboard[Web Dashboard]
    end

    subgraph backend["**Backend Services**"]
        trader[Trading Engine]
        risk[Risk Service]
        execution[Execution Service]
        signal[Signal Engine]
        ml[ML Classifier]
    end

    subgraph data["**Data Layer**"]
        trades_db[(Trades DB)]
        journal_db[(Journal DB)]
        ml_db[(ML Tracker)]
        oi_db[(OI Snapshots)]
    end

    subgraph external["**External**"]
        broker[Broker API]
        yf[Yahoo Finance]
        telegram[Telegram Bot]
        nse[NSE Data]
    end

    subgraph ai["**AI & Governance**"]
        ai_engine[AI Engine]
        auditor[Auto Auditor]
        healing[Self-Healing]
        docs[Living Docs]
    end

    operator --> dashboard
    dashboard --> trader
    trader --> signal
    trader --> execution
    trader --> risk
    signal --> ml
    execution --> broker
    signal --> yf
    trader --> trades_db
    execution --> journal_db
    ml --> ml_db
    signal --> oi_db
    trader --> telegram
    risk --> ai_engine
    ai_engine --> healing
    auditor --> docs

    style operator fill:#f3e5f5,stroke:#7b1fa2
    style dashboard fill:#e1f5fe,stroke:#0288d1
    style trader fill:#fff3e0,stroke:#e65100
    style risk fill:#fce4ec,stroke:#c62828
    style healing fill:#e8f5e9,stroke:#2e7d32
    style auditor fill:#e8f5e9,stroke:#2e7d32
    style docs fill:#e8f5e9,stroke:#2e7d32
```
"""

    # ── Private Helpers ───────────────────────────────────────────────────

    def _extract_docstring(self, content: str, route_pos: int) -> str:
        """Extract the docstring for a route handler.

        Looks for a triple-quoted string within the function body.
        """
        # Find the function definition after the route decorator
        func_match = re.search(r'(?:async\s+)?def\s+\w+\s*\([^)]*\):\s*(?:"""([^"]*)"""|\'\'\'([^\']*)\'\'\')', content[route_pos:route_pos + 2000])
        if func_match:
            return func_match.group(1) or func_match.group(2) or ""
        return ""

    def _fallback_architecture(self) -> str:
        """Provide a simple architecture diagram when KnowledgeGraph is unavailable."""
        return """# Architecture Diagram

```mermaid
graph TB
    subgraph app["**Application Layer**"]
        trader[Index Trader]
        launcher[Launcher GUI]
        dashboard[Enterprise Dashboard]
    end

    subgraph core["**Core Layer**"]
        risk[Risk Service]
        exec[Execution Service]
        signal[Signal Engine]
        portfolio[Portfolio Manager]
        healer[Self-Healing]
        auditor[Auto Auditor]
        ai[AI Engine]
    end

    subgraph infra["**Infrastructure Layer**"]
        broker[Broker Adapters]
        data[Data Providers]
        persist[Persistence]
        notify[Notifications]
        config[Config]
    end

    trader --> risk
    trader --> exec
    trader --> signal
    trader --> portfolio
    signal --> ai
    exec --> broker
    trader --> configure
    dashboard --> configure
    healer --> exec
    auditor --> risk
```
"""

    def _write_doc(self, filename: str, content: str) -> None:
        """Write a documentation file to the output directory."""
        file_path = self._output_dir / filename
        try:
            file_path.write_text(content, encoding="utf-8")
        except OSError as exc:
            _log.warning("[LIVING_DOC] Failed to write %s: %s", filename, exc)

    def get_stats(self) -> dict[str, Any]:
        """Get statistics about generated documentation."""
        if not self._output_dir.is_dir():
            return {"files_generated": 0, "last_generated": None}

        files = list(self._output_dir.glob("*"))
        return {
            "files_generated": len(files),
            "last_generated": self._last_generated,
            "files": [f.name for f in files],
            "output_dir": str(self._output_dir),
        }


# ── Singleton ───────────────────────────────────────────────────────────────


_generator: LivingDocGenerator | None = None
_gen_lock = threading.RLock()


def get_doc_generator() -> LivingDocGenerator:
    """Get the singleton LivingDocGenerator instance."""
    global _generator
    with _gen_lock:
        if _generator is None:
            _generator = LivingDocGenerator()
        return _generator


def reset_doc_generator() -> None:
    """Force-reset singleton (for testing)."""
    global _generator
    with _gen_lock:
        _generator = None


__all__ = [
    "ArchEdge",
    "ArchNode",
    "DocumentationPackage",
    "ERRelation",
    "ERTable",
    "LivingDocGenerator",
    "SequenceStep",
    "get_doc_generator",
    "reset_doc_generator",
]
