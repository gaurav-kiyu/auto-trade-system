"""
Regenerate docs/INTEGRATION_MANIFEST.md - full path + SHA256 parity vs upstream zips.

Run from project root:
  python scripts/generate_integration_manifest.py

Requires sibling zips under the parent of this project folder (same layout as AdvancedSystem):
  OPBuying_Scripts_13MAR2026_1.0.zip, ConsolidateVersion.zip
Optional extracted tree:
  ../_arcmp/final_integrated/user_code/OPBuying_Scripts_13MAR2026_1.0/
"""
from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def sibling(name: str) -> Path:
    return project_root().parent / name


def norm_zip_name(name: str) -> str:
    return name.replace("\\", "/").strip("/")


def skip_path(rel: str) -> bool:
    r = rel.replace("\\", "/")
    if not r:
        return True
    parts = r.split("/")
    if "__pycache__" in parts:
        return True
    if r.endswith(".pyc"):
        return True
    if ".pytest_cache" in parts:
        return True
    if parts[0] in {".git", ".svn"}:
        return True
    if r.endswith((".db", ".log", ".jsonl")):
        return True
    if r in {"trader_state.json", "trader_state.json.bak", "_runtime_output.txt"}:
        return True
    if r.startswith("logs/") or r.startswith("backups/") or r.startswith("reports/"):
        return True
    if r.endswith(".exe"):
        return True
    return False


def tree_files(root: Path) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if skip_path(rel):
            continue
        out[rel] = p
    return out


def zip_files(zpath: Path, strip_prefix: str) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    strip_prefix = strip_prefix.strip("/")
    with zipfile.ZipFile(zpath) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = norm_zip_name(info.filename)
            pref = strip_prefix + "/"
            if strip_prefix:
                if name.startswith(pref):
                    inner = name[len(pref) :].strip("/")
                elif name == strip_prefix:
                    inner = ""
                else:
                    continue
            else:
                inner = name.strip("/")
            if not inner or skip_path(inner):
                continue
            with zf.open(info) as fh:
                out[inner] = fh.read()
    return out


def sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def fmt_set(title: str, items: set[str], lines: list[str]) -> None:
    s = sorted(items)
    lines.append(f"### {title} ({len(s)})\n\n")
    if not s:
        lines.append("_None._\n\n")
        return
    for x in s:
        lines.append(f"- `{x}`\n")
    lines.append("\n")


def main() -> None:
    final = project_root()
    final_files = tree_files(final)
    final_set = set(final_files)

    lines: list[str] = []
    lines.append("# Integration manifest (automated)\n\n")
    lines.append(
        "Regenerate this file with:\n\n```bash\npython scripts/generate_integration_manifest.py\n```\n\n"
    )
    lines.append(
        f"**Final tree:** `{final.name}/`\n\n"
        "**Skipped in all comparisons:** `__pycache__/`, `*.pyc`, `.pytest_cache/`, `*.db`, `*.log`, "
        "`*.jsonl`, `logs/`, `backups/`, `reports/`, `trader_state*.json`, `_runtime_output.txt`, `*.exe`.\n\n"
    )

    z0 = sibling("OPBuying_Scripts_13MAR2026_1.0.zip")
    if z0.is_file():
        z0_files = zip_files(z0, "OPBuying_Scripts_13MAR2026_1.0")
        z0_set = set(z0_files)
        only_zip = z0_set - final_set
        only_final = final_set - z0_set
        same = {k for k in z0_set & final_set if sha_bytes(z0_files[k]) == sha_bytes(final_files[k].read_bytes())}
        diff = (z0_set & final_set) - same
        lines.append("## vs `OPBuying_Scripts_13MAR2026_1.0.zip`\n\n")
        fmt_set("In **1.0 zip** but missing from **final** (gap if non-excluded)", only_zip, lines)
        fmt_set("In **final** but not in **1.0 zip** (expected: upgrades + docs)", only_final, lines)
        fmt_set("Same content (SHA256) in both", same, lines)
        fmt_set("Same path, **different** content (final is newer / hardened)", diff, lines)
    else:
        lines.append("## vs `OPBuying_Scripts_13MAR2026_1.0.zip`\n\n_Zip not found next to project folder._\n\n")

    zc = sibling("ConsolidateVersion.zip")
    if zc.is_file():
        zc_files = zip_files(zc, "ConsolidateVersion")
        zc_set = set(zc_files)
        only_zip = zc_set - final_set
        only_final = final_set - zc_set
        same = {k for k in zc_set & final_set if sha_bytes(zc_files[k]) == sha_bytes(final_files[k].read_bytes())}
        diff = (zc_set & final_set) - same
        lines.append("## vs `ConsolidateVersion.zip`\n\n")
        fmt_set("In **Consolidate** zip but missing from **final**", only_zip, lines)
        fmt_set("In **final** but not in **Consolidate** zip", only_final, lines)
        fmt_set("Same content in both", same, lines)
        fmt_set("Same path, **different** content", diff, lines)
    else:
        lines.append("## vs `ConsolidateVersion.zip`\n\n_Zip not found next to project folder._\n\n")

    embedded = sibling("_arcmp") / "final_integrated" / "user_code" / "OPBuying_Scripts_13MAR2026_1.0"
    if embedded.is_dir():
        emb_files = tree_files(embedded)
        emb_set = set(emb_files)
        only_emb = emb_set - final_set
        only_final = final_set - emb_set
        same = {k for k in emb_set & final_set if sha_bytes(emb_files[k].read_bytes()) == sha_bytes(final_files[k].read_bytes())}
        diff = (emb_set & final_set) - same
        lines.append("## vs `final_integrated` embedded `user_code/OPBuying_Scripts_13MAR2026_1.0/`\n\n")
        fmt_set("In **embedded 1.0** but missing from **final**", only_emb, lines)
        fmt_set("In **final** but not in **embedded 1.0**", only_final, lines)
        fmt_set("Same content in both", same, lines)
        fmt_set("Same path, **different** content", diff, lines)
    else:
        lines.append("## vs embedded `final_integrated` tree\n\n")
        lines.append("_Path `_arcmp/final_integrated/user_code/OPBuying_Scripts_13MAR2026_1.0/` not found._\n\n")

    fi_root = sibling("_arcmp") / "final_integrated"
    if fi_root.is_dir():
        extra: list[str] = []
        for p in fi_root.rglob("*"):
            if not p.is_file():
                continue
            rel = p.relative_to(fi_root).as_posix()
            if rel.startswith("user_code/"):
                continue
            if skip_path(rel):
                continue
            extra.append(rel)
        lines.append("## `final_integrated_trading_system` outside `user_code/` (not merged)\n\n")
        if not extra:
            lines.append("_None._\n\n")
        else:
            for x in sorted(extra):
                lines.append(f"- `{x}`\n")
            lines.append("\n")
            lines.append(
                "> Stub **app/** - must not replace this product’s real modules.\n\n"
            )

    lines.append("## Conclusion\n\n")
    lines.append(
        "- **Gap rule:** any path under `core/`, `index_app/`, `tests/`, `scripts/`, `templates/`, or root `*.py` "
        "that appears **only in an upstream zip** and **not in final** is a defect - current run should show **0**.\n"
    )
    lines.append("- **Excluded artifacts** (DB, logs, EXE, caches) are not required to match.\n")

    out = final / "docs" / "INTEGRATION_MANIFEST.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(lines), encoding="utf-8")
    print("Wrote", out)


if __name__ == "__main__":
    main()
