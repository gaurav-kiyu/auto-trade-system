#!/usr/bin/env python3
"""Cross-platform Mutation Testing Script.
Applies simple mutation operators to Python source files and runs their
associated test suites to determine mutation score (killed / survived).
Works on Windows natively (no WSL required).

Usage:
    python scripts/run_mutation_tests.py --target core/services/risk_service.py
    python scripts/run_mutation_tests.py --target core/services/ --timeout 30
    python scripts/run_mutation_tests.py --list-targets
"""

import ast
import glob
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# ── Mutant Class ──────────────────────────────────────────────────────────────

class Mutant:
    def __init__(self, mutant_id: str, operator: str, location: str,
                 original_line: str, mutated_line: str):
        self.id = mutant_id
        self.operator = operator
        self.location = location
        self.original_line = original_line
        self.mutated_line = mutated_line
        self.status: str = "PENDING"


# ── AST-based mutation engine ─────────────────────────────────────────────────

_OP_RULES: dict = {
    ast.Gt:    (ast.GtE,  ">"),   # >  → >=
    ast.GtE:   (ast.Gt,   ">="),  # >= → >
    ast.Lt:    (ast.LtE,  "<"),   # <  → <=
    ast.LtE:   (ast.Lt,   "<="),  # <= → <
    ast.Eq:    (ast.NotEq, "=="), # == → !=
    ast.NotEq: (ast.Eq,   "!="),  # != → ==
    ast.And:   (ast.Or,   "and"), # and → or
    ast.Or:    (ast.And,  "or"),  # or  → and
    ast.Add:   (ast.Sub,  "+"),   # +  → -
    ast.Sub:   (ast.Add,  "-"),   # -  → +
}

_OP_RULE_NAMES: dict = {
    ast.Gt:    "replace_gt_with_ge",
    ast.GtE:   "replace_ge_with_gt",
    ast.Lt:    "replace_lt_with_le",
    ast.LtE:   "replace_le_with_lt",
    ast.Eq:    "replace_eq_with_neq",
    ast.NotEq: "replace_neq_with_eq",
    ast.And:   "replace_and_with_or",
    ast.Or:    "replace_or_with_and",
    ast.Add:   "replace_add_with_sub",
    ast.Sub:   "replace_sub_with_add",
}

_OP_NEW_SYMBOL: dict = {
    ast.GtE:  ">=",
    ast.Gt:   ">",
    ast.LtE:  "<=",
    ast.Lt:   "<",
    ast.NotEq: "!=",
    ast.Eq:   "==",
    ast.Or:   "or",
    ast.And:  "and",
    ast.Sub:  "-",
    ast.Add:  "+",
}


def _generate_mutants(filepath: str) -> list[Mutant]:
    mutants: list[Mutant] = []
    try:
        with open(filepath, encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source, filename=filepath)
    except (SyntaxError, UnicodeDecodeError) as e:
        print(f"  Parse error in {filepath}: {e}")
        return mutants

    source_lines = source.splitlines()
    mutant_id = 0

    def _find_nth_occurrence(text: str, pattern: str, n: int) -> int:
        idx = -1
        for _ in range(n + 1):
            idx = text.find(pattern, idx + 1)
            if idx < 0:
                return -1
        return idx

    def _add_mutant(node: ast.AST, old_type: type, occurrence: int = 0) -> None:
        nonlocal mutant_id
        if old_type not in _OP_RULES:
            return
        new_op_cls, old_symbol = _OP_RULES[old_type]
        lineno = getattr(node, "lineno", 0)
        if not lineno or lineno > len(source_lines):
            return
        line = source_lines[lineno - 1]
        new_symbol = _OP_NEW_SYMBOL[new_op_cls]
        idx = _find_nth_occurrence(line, old_symbol, occurrence)
        if idx >= 0:
            mutated_line = line[:idx] + new_symbol + line[idx + len(old_symbol):]
            if mutated_line != line:
                mutant_id += 1
                mutants.append(Mutant(
                    mutant_id=f"MUT-{mutant_id:04d}",
                    operator=_OP_RULE_NAMES.get(old_type, "unknown"),
                    location=f"{Path(filepath).name}:{lineno}",
                    original_line=line,
                    mutated_line=mutated_line,
                ))

    occurrence_counters: dict[tuple[int, type], int] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for op in node.ops:
                op_type = type(op)
                if op_type not in _OP_RULES:
                    continue
                lineno = getattr(node, "lineno", 0)
                occ = occurrence_counters.get((lineno, op_type), 0)
                _add_mutant(node, op_type, occurrence=occ)
                occurrence_counters[(lineno, op_type)] = occ + 1
        elif isinstance(node, ast.BoolOp):
            _add_mutant(node, type(node.op))
        elif isinstance(node, ast.BinOp):
            _add_mutant(node, type(node.op))

    seen = set()
    unique = []
    for m in mutants:
        key = (m.location, m.operator, m.mutated_line)
        if key not in seen:
            seen.add(key)
            unique.append(m)
    return unique


def _apply_mutant(source: str, mutant: Mutant) -> str:
    lines = source.splitlines()
    parts = mutant.location.split(":")
    if len(parts) >= 2:
        try:
            lineno = int(parts[1]) - 1
            if 0 <= lineno < len(lines):
                lines[lineno] = mutant.mutated_line
        except (ValueError, IndexError):
            pass
    return "\n".join(lines)


# ── Core mutation test runner ─────────────────────────────────────────────────

def run_mutation_test(
    filepath: str,
    test_pattern: str | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    filepath = os.path.abspath(filepath)
    if not os.path.exists(filepath):
        return {"error": f"File not found: {filepath}", "score": 0.0}

    filename = os.path.splitext(os.path.basename(filepath))[0]
    if test_pattern is None:
        module_name = filename.replace("test_", "").replace("_test", "")
        test_pattern = f"tests/test_{module_name}.py"
        # Discover all matching test files using glob (systemic fix for dual-file issue)
        test_files_found = sorted(glob.glob(f"tests/test_*{module_name}.py"))
        if len(test_files_found) > 1 or (len(test_files_found) == 1 and test_files_found[0] != test_pattern):
            test_pattern = test_files_found

    with open(filepath, encoding="utf-8") as f:
        original_source = f.read()

    mutants = _generate_mutants(filepath)
    if not mutants:
        test_path = test_pattern.replace("*", "") if isinstance(test_pattern, str) else test_pattern[0]
        if not os.path.exists(test_path):
            return {"error": "No test file found", "score": -1.0}
        return {"score": 100.0, "killed": 0, "survived": 0, "total": 0,
                "message": "No applicable mutations found"}

    results = {"killed": 0, "survived": 0, "error": 0, "timeout": 0, "total": len(mutants)}
    if isinstance(test_pattern, list):
        test_label = ", ".join(test_pattern)
        pytest_cmd = [sys.executable, "-m", "pytest"] + test_pattern + ["-q", "--tb=line", "--no-header", "-x"]
    else:
        test_label = test_pattern
        pytest_cmd = [sys.executable, "-m", "pytest", test_pattern, "-q", "--tb=line", "--no-header", "-x"]
    print(f"\n  Running {len(mutants)} mutants against {test_label}...")

    for mutant in mutants:
        mutated_source = _apply_mutant(original_source, mutant)
        try:
            # Write mutated source directly (avoid backup/restore chain that causes Windows file locking issues)
            import tempfile
            fd, tmp_path = tempfile.mkstemp(suffix='.py', dir=os.path.dirname(filepath))
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    f.write(mutated_source)
                # Atomically replace the original with the mutated copy
                os.replace(tmp_path, filepath)
            except Exception as e:
                # Clean up temp file if replace fails
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                mutant.status = "ERROR"
                results["error"] += 1
                print(f"  [ERROR] {mutant.id}: failed to write mutation: {e}")
                continue

            start = time.time()
            proc = subprocess.run(
                pytest_cmd,
                capture_output=True, text=True, timeout=timeout,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                cwd=os.getcwd(),
            )
            elapsed = time.time() - start

            if proc.returncode == 0:
                mutant.status = "SURVIVED"
                results["survived"] += 1
                print(f"  [SURVIVED] {mutant.id} ({elapsed:.1f}s) @ {mutant.location})")
            else:
                mutant.status = "KILLED"
                results["killed"] += 1

        except subprocess.TimeoutExpired:
            mutant.status = "TIMEOUT"
            results["timeout"] += 1
        except Exception as e:
            mutant.status = "ERROR"
            results["error"] += 1
            print(f"  [ERROR] {mutant.id}: {e}")
        finally:
            # Always restore original source by writing directly
            try:
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(original_source)
            except OSError as e:
                print(f"  [WARN] Source restore failed: {e}")

    score = (results["killed"] / results["total"] * 100) if results["total"] > 0 else 0.0
    results["score"] = round(score, 1)
    print(f"\n  Score: {results['score']:.1f}% "
          f"(killed={results['killed']}/{results['total']}, "
          f"survived={results['survived']})")
    _cleanup_test_artifacts()
    return results


def find_target_files(target: str) -> list[str]:
    target = os.path.normpath(target)
    if os.path.isfile(target) and target.endswith(".py"):
        return [target]
    if os.path.isdir(target):
        files = []
        for root, _, filenames in os.walk(target):
            for fn in filenames:
                if fn.endswith(".py") and not fn.startswith("__"):
                    files.append(os.path.join(root, fn))
        return sorted(files)
    return sorted(glob.glob(target, recursive=True))


# ── CLI ───────────────────────────────────────────────────────────────────────

def _cleanup_test_artifacts() -> None:
    for pattern in ["test_recon_*.db", "nonexistent_*.db"]:
        for f in glob.glob(pattern):
            try:
                os.remove(f)
            except OSError:
                pass


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Cross-platform mutation testing.")
    parser.add_argument("--target", default="core/services/risk_service.py",
                        help="Target file or directory")
    parser.add_argument("--test", default=None, help="Specific test pattern")
    parser.add_argument("--timeout", type=int, default=30, help="Per-mutant timeout")
    parser.add_argument("--list-targets", action="store_true", help="List targets")
    args = parser.parse_args()

    if args.list_targets:
        for root, dirs, files in os.walk("core"):
            for fn in files:
                if fn.endswith(".py") and not fn.startswith("__"):
                    print(os.path.join(root, fn))
        for root, dirs, files in os.walk("scripts"):
            for fn in files:
                if fn.endswith(".py") and not fn.startswith("__"):
                    print(os.path.join(root, fn))
        return

    files = find_target_files(args.target)
    if not files:
        print(f"No target files found: {args.target}")
        return

    all_results = []
    for fp in files:
        print(f"\n{'='*60}")
        print(f"Mutation testing: {fp}")
        print(f"{'='*60}")
        result = run_mutation_test(fp, test_pattern=args.test, timeout=args.timeout)
        all_results.append(result)

    total_killed = sum(r.get("killed", 0) for r in all_results)
    total_survived = sum(r.get("survived", 0) for r in all_results)
    total_mutants = sum(r.get("total", 0) for r in all_results)
    scores = [r.get("score", 0) for r in all_results if r.get("score", 0) >= 0]
    avg_score = sum(scores) / len(scores) if scores else 0.0

    print(f"\n{'='*60}")
    print("MUTATION TEST SUMMARY")
    print(f"{'='*60}")
    print(f"  Files tested:   {len(all_results)}")
    print(f"  Total mutants:  {total_mutants}")
    print(f"  Killed:         {total_killed}")
    print(f"  Survived:       {total_survived}")
    print(f"  Average score:  {avg_score:.1f}%")


if __name__ == "__main__":
    main()
