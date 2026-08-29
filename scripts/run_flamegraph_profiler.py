#!/usr/bin/env python3
"""Performance Flamegraph Profiler (Phase 5).

Generates CPU flamegraphs and performance profiles for OPB trading system
using cProfile, py-spy, or built-in profiler. Produces SVG flamegraphs,
text call trees, and JSON performance reports.

Supports three profiling modes:
  1. profile_import  : Measure module import times (cold-start simulation)
  2. profile_module  : Profile a specific function/module
  3. profile_system  : Profile the full trading system for N seconds

Usage:
    python scripts/run_flamegraph_profiler.py import          # Profile imports
    python scripts/run_flamegraph_profiler.py module core.risk_service.evaluate_trade
    python scripts/run_flamegraph_profiler.py system 5        # Profile 5 seconds
    python scripts/run_flamegraph_profiler.py --all            # Run all profiles
    python scripts/run_flamegraph_profiler.py import --json    # JSON output
    python scripts/run_flamegraph_profiler.py --ci             # CI mode
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

_log = logging.getLogger("flamegraph_profiler")

_REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"

# Critical modules for cold-start profiling
_CRITICAL_MODULES = [
    "core.datetime_ist",
    "core.config_bootstrap",
    "core.performance_metrics",
    "core.monte_carlo",
    "core.pure_index_signal",
    "core.adaptive_signal",
    "core.strike_selector",
    "core.iv_rank",
    "core.session_classifier",
    "core.ml_classifier",
    "core.signal_autopsy",
    "core.metrics_exporter",
    "core.services.risk_service",
    "core.adapters.broker_adapters",
    "core.services.paper_trader",
    "core.report_generator",
    "core.health_checker",
    "core.trade_journal",
]

_SVG_TEMPLATE = """<?xml version="1.0" standalone="no"?>
<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">
<svg version="1.1" width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">
<defs>
  <linearGradient id="header" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0%" stop-color="#1a237e"/>
    <stop offset="100%" stop-color="#3949ab"/>
  </linearGradient>
</defs>
<rect width="{width}" height="{height}" fill="white"/>
<rect width="{width}" height="40" fill="url(#header)"/>
<text x="10" y="25" fill="white" font-family="Arial" font-size="14" font-weight="bold">{title}</text>
<text x="{width_right}" y="25" fill="rgba(255,255,255,0.8)" font-family="Arial" font-size="11" text-anchor="end">{subtitle}</text>
{body}
<rect y="{height}-20" width="{width}" height="20" fill="#f5f5f5"/>
<text x="10" y="{height}-6" fill="#666" font-family="Arial" font-size="10">{legend}</text>
</svg>"""


# ── Profile: Module Import Times ──────────────────────────────────────────────


def profile_imports(
    modules: list[str] | None = None,
    iterations: int = 1,
) -> dict[str, Any]:
    """Profile module import times for cold-start simulation."""
    if modules is None:
        modules = _CRITICAL_MODULES

    all_results: list[dict[str, float]] = []
    for _ in range(iterations):
        iteration_results: dict[str, float] = {}
        for mod_name in modules:
            try:
                # Ensure fresh import by tracking first import
                if mod_name in sys.modules:
                    elapsed = 0.0  # Already cached
                else:
                    start = time.perf_counter()
                    __import__(mod_name)
                    elapsed = time.perf_counter() - start
                iteration_results[mod_name] = round(elapsed * 1000, 3)  # ms
            except Exception:
                iteration_results[mod_name] = -1.0  # Error indicator
        all_results.append(iteration_results)

    # Aggregate
    if not all_results:
        return {"error": "No results", "modules": {}}

    final: dict[str, Any] = {}
    for mod_name in modules:
        times = [r.get(mod_name, 0) for r in all_results if r.get(mod_name, -1) >= 0]
        if not times:
            final[mod_name] = {"avg_ms": -1, "error": "import failed"}
        else:
            final[mod_name] = {
                "avg_ms": round(sum(times) / len(times), 3),
                "min_ms": round(min(times), 3),
                "max_ms": round(max(times), 3),
            }

    total_avg = sum(v["avg_ms"] for v in final.values() if isinstance(v.get("avg_ms"), (int, float)) and v["avg_ms"] > 0)
    cached_count = sum(1 for mod_name in modules if mod_name in sys.modules)

    return {
        "type": "import_profile",
        "iterations": iterations,
        "modules_tested": len(modules),
        "modules_already_cached": cached_count,
        "total_import_time_ms": round(total_avg, 2),
        "modules": final,
    }


# ── Profile: Module/Function ──────────────────────────────────────────────────


def profile_module(module_path: str, iterations: int = 10) -> dict[str, Any]:
    """Profile a specific function/module using cProfile."""
    parts = module_path.split(".")
    if len(parts) < 2:
        return {"error": f"Invalid module path: {module_path}. Use e.g. core.risk_service.evaluate_trade"}

    # Extract module and function
    func_name = parts[-1]
    mod_name = ".".join(parts[:-1])

    # Import the module
    try:
        __import__(mod_name)
        mod = sys.modules[mod_name]
        func = getattr(mod, func_name, None)
        if func is None:
            return {"error": f"Function '{func_name}' not found in '{mod_name}'"}
    except Exception as e:
        return {"error": f"Import failed: {e}"}

    import cProfile
    import io
    import pstats

    results = []
    for i in range(iterations):
        profiler = cProfile.Profile()
        try:
            profiler.enable()
            if callable(func):
                func()
            profiler.disable()
        except Exception as e:
            results.append({"iteration": i + 1, "error": str(e)})
            continue

        s = io.StringIO()
        ps = pstats.Stats(profiler, stream=s).sort_stats("cumtime")
        ps.print_stats(10)

        # Extract key metrics
        total_time = ps.total_tt
        call_count = ps.total_calls

        results.append({
            "iteration": i + 1,
            "total_time_s": round(total_time, 6),
            "call_count": call_count,
            "stats_preview": s.getvalue()[:500],
        })

    times = [r["total_time_s"] for r in results if "error" not in r]
    return {
        "type": "module_profile",
        "module_path": module_path,
        "iterations": iterations,
        "succeeded": len(times),
        "avg_time_s": round(sum(times) / len(times), 6) if times else 0.0,
        "min_time_s": round(min(times), 6) if times else 0.0,
        "max_time_s": round(max(times), 6) if times else 0.0,
        "results": results,
    }


# ── Profile: System (wall-clock) ──────────────────────────────────────────────


def profile_system(duration_s: int = 5) -> dict[str, Any]:
    """Profile system for N seconds using time-based sampling."""
    import threading

    # Collect sample data
    samples: list[dict[str, Any]] = []
    lock = threading.Lock()
    stop_event = threading.Event()

    def _sampler() -> None:
        import traceback
        while not stop_event.is_set():
            frame = sys._getframe(2) if hasattr(sys, "_getframe") else None
            if frame:
                stack = traceback.format_stack(frame)
                stack_str = "".join(stack[-5:])  # Last 5 frames
            else:
                stack_str = "<no frame>"
            with lock:
                samples.append({
                    "time": time.time(),
                    "stack": stack_str[:200],
                })
            time.sleep(0.01)  # 100Hz sampling

    sampler = threading.Thread(target=_sampler, daemon=True)
    sampler.start()

    print(f"  Profiling system for {duration_s}s at 100Hz...")
    time.sleep(duration_s)
    stop_event.set()
    sampler.join(timeout=2)

    with lock:
        total_samples = len(samples)

    # Aggregate stack frequency
    from collections import Counter
    stack_counts: Counter = Counter()
    for s in samples:
        # Use first unique frame as key
        lines = s["stack"].strip().split("\n")
        key = lines[-1] if lines else "<unknown>"
        stack_counts[key] += 1

    top_stacks = stack_counts.most_common(20)

    return {
        "type": "system_profile",
        "duration_s": duration_s,
        "sample_rate_hz": 100,
        "total_samples": total_samples,
        "top_stacks": [
            {"frame": frame, "count": count, "pct": round(count / total_samples * 100, 1)}
            for frame, count in top_stacks
        ],
    }


# ── SVG Flamegraph Generator ──────────────────────────────────────────────────


def generate_flamegraph_svg(
    profile_data: dict[str, Any],
    title: str = "OPB Performance Flamegraph",
) -> str:
    """Generate an SVG flamegraph from profile data."""
    if "error" in profile_data:
        return f"<svg><text x='10' y='20'>Error: {profile_data['error']}</text></svg>"

    width = 800
    row_height = 20
    header_height = 40
    footer_height = 20

    if profile_data.get("type") == "import_profile":
        modules = profile_data.get("modules", {})
        items = [
            (name, data.get("avg_ms", 0))
            for name, data in modules.items()
            if isinstance(data.get("avg_ms"), (int, float)) and data["avg_ms"] >= 0
        ]
        items.sort(key=lambda x: -x[1])  # Sort by time descending
        max_val = items[0][1] if items else 1.0
        total = profile_data.get("total_import_time_ms", 0)

        body_parts: list[str] = []
        y = header_height + 10
        for name, avg_ms in items:
            bar_width = max((avg_ms / max_val) * (width - 40), 2)
            intensity = min(int(avg_ms / max_val * 200 + 55), 255)
            color = f"rgb({intensity}, {max(40, 255 - intensity)}, 64)"
            body_parts.append(
                f'<rect x="20" y="{y}" width="{bar_width:.0f}" height="{row_height - 2}" '
                f'fill="{color}" rx="2">'
                f'<title>{name}: {avg_ms:.3f}ms</title></rect>'
                f'<text x="25" y="{y + 14}" fill="white" font-family="monospace" font-size="10" '
                f'text-anchor="start">{name} ({avg_ms:.3f}ms)</text>'
            )
            y += row_height

        height = y + footer_height + 10
        body = "\n".join(body_parts)
        legend = f"Total import time: {total:.2f}ms | Modules: {len(items)} | Width scaled to max={max_val:.3f}ms"

    elif profile_data.get("type") == "module_profile":
        results = profile_data.get("results", [])
        avg = profile_data.get("avg_time_s", 0)
        items = [(r.get("iteration", 0), r.get("total_time_s", 0))
                 for r in results if "error" not in r]
        max_val = max((v for _, v in items), default=1.0)

        body_parts = []
        y = header_height + 10
        for it_num, t in items:
            bar_width = max((t / max_val) * (width - 40), 2)
            color = "#3949ab" if t <= avg * 1.1 else "#e53935"
            body_parts.append(
                f'<rect x="20" y="{y}" width="{bar_width:.0f}" height="{row_height - 2}" '
                f'fill="{color}" rx="2">'
                f'<title>Iteration {it_num}: {t:.6f}s</title></rect>'
                f'<text x="25" y="{y + 14}" fill="white" font-family="monospace" font-size="10">'
                f'Iteration {it_num}: {t:.6f}s</text>'
            )
            y += row_height

        height = y + footer_height + 10
        body = "\n".join(body_parts)
        legend = f"Avg: {avg:.6f}s | Min: {profile_data.get('min_time_s', 0):.6f}s | Max: {profile_data.get('max_time_s', 0):.6f}s"

    elif profile_data.get("type") == "system_profile":
        stacks = profile_data.get("top_stacks", [])
        max_count = stacks[0]["count"] if stacks else 1

        body_parts = []
        y = header_height + 10
        for s in stacks:
            frame = s.get("frame", "")[:60]
            count = s.get("count", 0)
            pct = s.get("pct", 0)
            bar_width = max((count / max_count) * (width - 40), 2)
            intensity = min(int(pct * 2 + 55), 255)
            color = f"rgb({255 - intensity}, 64, {intensity})"
            body_parts.append(
                f'<rect x="20" y="{y}" width="{bar_width:.0f}" height="{row_height - 2}" '
                f'fill="{color}" rx="2">'
                f'<title>{frame}: {count} samples ({pct}%)</title></rect>'
                f'<text x="25" y="{y + 14}" fill="white" font-family="monospace" font-size="9">'
                f'{frame} — {count} ({pct}%)</text>'
            )
            y += row_height

        height = y + footer_height + 10
        body = "\n".join(body_parts)
        samples = profile_data.get("total_samples", 0)
        duration = profile_data.get("duration_s", 0)
        legend = f"Samples: {samples} over {duration}s | Top {len(stacks)} stacks shown | Width scaled to max={max_count}"

    else:
        return f"<svg><text x='10' y='20'>Unsupported profile type: {profile_data.get('type')}</text></svg>"

    return _SVG_TEMPLATE.format(
        width=width,
        height=height,
        title=title,
        subtitle=profile_data.get("type", "").replace("_", " ").title(),
        width_right=width - 10,
        body=body,
        legend=legend,
    )


# ── CLI ────────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="OPB Performance Flamegraph Profiler",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("mode", nargs="?", default="import",
                        choices=["import", "module", "system", "all"],
                        help="Profiling mode (default: import)")
    parser.add_argument("target", nargs="?", default=None,
                        help="Module path for 'module' mode, or seconds for 'system' mode")
    parser.add_argument("--iterations", type=int, default=3,
                        help="Iterations for import/module profiling")
    parser.add_argument("--ci", action="store_true",
                        help="CI mode: fail if cold-start import > 5s")
    parser.add_argument("--json", action="store_true",
                        help="Output JSON report")
    parser.add_argument("--svg", action="store_true", default=True,
                        help="Generate SVG flamegraph (default: True)")
    args = parser.parse_args()

    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {}

    if args.mode in ("import", "all"):
        print(f"\n  Profiling module imports ({args.iterations} iteration(s))...")
        import_profile = profile_imports(iterations=args.iterations)
        results["import_profile"] = import_profile

        total = import_profile.get("total_import_time_ms", 0)
        print(f"  Total cold-start import time: {total:.2f}ms")

        if import_profile.get("modules"):
            print("  Top 5 slowest imports:")
            modules = import_profile["modules"]
            sorted_mods = sorted(
                [(n, d) for n, d in modules.items() if isinstance(d.get("avg_ms"), (int, float)) and d["avg_ms"] >= 0],
                key=lambda x: -x[1]["avg_ms"],
            )[:5]
            for name, data in sorted_mods:
                print(f"    {name}: {data['avg_ms']:.3f}ms")

        if args.svg:
            svg = generate_flamegraph_svg(import_profile, "OPB Import Profile")
            svg_path = _REPORTS_DIR / "flamegraph_import.svg"
            svg_path.write_text(svg, encoding="utf-8")
            print(f"  SVG flamegraph: {svg_path}")

    if args.mode in ("module", "all"):
        target = args.target or "core.performance_metrics.compute_metrics"
        print(f"\n  Profiling module: {target} ({args.iterations} iterations)...")
        mod_profile = profile_module(target, iterations=args.iterations)
        results["module_profile"] = mod_profile

        if "error" not in mod_profile:
            print(f"  Avg: {mod_profile.get('avg_time_s', 0):.6f}s  "
                  f"Min: {mod_profile.get('min_time_s', 0):.6f}s  "
                  f"Max: {mod_profile.get('max_time_s', 0):.6f}s")

            if args.svg:
                svg = generate_flamegraph_svg(mod_profile, f"OPB Module Profile: {target}")
                svg_path = _REPORTS_DIR / f"flamegraph_{target.replace('.', '_')}.svg"
                svg_path.write_text(svg, encoding="utf-8")
                print(f"  SVG flamegraph: {svg_path}")

    if args.mode in ("system", "all"):
        duration = int(args.target) if args.target and args.target.isdigit() else 5
        print(f"\n  Profiling system for {duration}s...")
        sys_profile = profile_system(duration_s=duration)
        results["system_profile"] = sys_profile

        samples = sys_profile.get("total_samples", 0)
        print(f"  Samples collected: {samples}")
        for s in sys_profile.get("top_stacks", [])[:5]:
            print(f"    {s.get('frame', '')[:60]} — {s.get('count', 0)} ({s.get('pct', 0):.1f}%)")

        if args.svg:
            svg = generate_flamegraph_svg(sys_profile, "OPB System Profile")
            svg_path = _REPORTS_DIR / "flamegraph_system.svg"
            svg_path.write_text(svg, encoding="utf-8")
            print(f"  SVG flamegraph: {svg_path}")

    # JSON output
    if args.json:
        print(json.dumps(results, indent=2, default=str))

    # Write combined JSON report
    report_path = _REPORTS_DIR / "flamegraph_report.json"
    report_path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"\n  JSON report: {report_path}")

    # CI check: fail if cold-start import > 5 seconds
    if args.ci:
        import_total = results.get("import_profile", {}).get("total_import_time_ms", 0)
        if import_total > 5000:
            print(f"  [CI FAIL] Cold-start import time {import_total:.0f}ms exceeds 5000ms threshold")
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
