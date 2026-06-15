"""Scan for remaining bare except:, except Exception:, and pass-only except blocks."""
import os
import re
import sys


def scan_exceptions(start_dir: str = "."):
    """Walk directory tree and find problematic exception blocks."""
    results = []
    for root, dirs, files in os.walk(start_dir):
        # Skip hidden dirs, virtual environments, generated dirs
        dirs[:] = [
            d
            for d in dirs
            if not d.startswith(".")
            and d
            not in (
                "venv",
                "__pycache__",
                "logs",
                "dist",
                "node_modules",
                ".git",
                "site-packages",
                ".mypy_cache",
                ".pytest_cache",
                ".ruff_cache",
            )
        ]
        for f in sorted(files):
            if not f.endswith(".py") or f.startswith("__"):
                continue
            path = os.path.join(root, f)
            try:
                content = open(path, encoding="utf-8", errors="ignore").read()
            except (OSError, UnicodeDecodeError):
                continue

            lines = content.split("\n")

            bare_except = 0
            generic_except = 0
            pass_only_except = 0
            pass_only_nonpass = 0

            i = 0
            while i < len(lines):
                line = lines[i]
                stripped = line.strip()
                # Skip comments
                if stripped.startswith("#"):
                    i += 1
                    continue

                # Check for bare except:
                if re.match(r"^\s*except\s*:", line) and not stripped.startswith("#"):
                    bare_except += 1
                    if i + 1 < len(lines) and re.match(r"^\s*pass\s*(#.*)?$", lines[i + 1]):
                        pass_only_except += 1
                    elif i + 1 < len(lines) and not re.match(
                        r"^\s*(pass|raise|continue|break|return|log|self\._log|print)\s",
                        lines[i + 1],
                    ):
                        pass_only_nonpass += 1

                # Check for generic except Exception:
                elif re.match(r"^\s*except\s+Exception\s*:", line) and not stripped.startswith("#"):
                    generic_except += 1
                    if i + 1 < len(lines) and re.match(r"^\s*pass\s*(#.*)?$", lines[i + 1]):
                        pass_only_except += 1
                    elif i + 1 < len(lines) and not re.match(
                        r"^\s*(pass|raise|continue|break|return|log|self\._log|print)\s",
                        lines[i + 1],
                    ):
                        pass_only_nonpass += 1

                i += 1

            if bare_except > 0 or generic_except > 0:
                results.append((path, bare_except, generic_except, pass_only_except, pass_only_nonpass))

    total_bare = sum(r[1] for r in results)
    total_generic = sum(r[2] for r in results)
    total_pass = sum(r[3] for r in results)
    total_nonpass = sum(r[4] for r in results)

    print("=" * 70)
    print(f"EXCEPTION AUDIT - {start_dir}")
    print("=" * 70)
    print(f"  Bare except: blocks:              {total_bare}")
    print(f"  Generic except Exception: blocks:  {total_generic}")
    print(f"  Pass-only except blocks:          {total_pass}")
    print(f"  Non-pass except blocks:           {total_nonpass}")
    print(f"  Files with issues:                {len(results)}")

    if total_bare:
        print(f"\n  --- Files with bare except: ({total_bare}) ---")
        for p, b, g, pa, npa in sorted(results):
            if b:
                print(f"    {p}  [bare:{b} gen:{g} pass:{pa} other:{npa}]")

    if total_generic:
        print(f"\n  --- Files with generic except Exception: ({total_generic}) ---")
        for p, b, g, pa, npa in sorted(results):
            if g:
                print(f"    {p}  [bare:{b} gen:{g} pass:{pa} other:{npa}]")

    if results:
        print(f"\n  --- ALL files with issues sorted ---")
        for p, b, g, pa, npa in sorted(results):
            print(f"    {p}  [bare:{b} gen:{g} pass:{pa} other:{npa}]")

    return results


if __name__ == "__main__":
    start = sys.argv[1] if len(sys.argv) > 1 else "."
    scan_exceptions(start)
