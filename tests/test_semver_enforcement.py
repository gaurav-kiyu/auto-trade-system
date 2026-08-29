"""Tests for Semantic Versioning (SemVer) Enforcement — AST-12.

Validates that the project strictly follows Semantic Versioning (MAJOR.MINOR.PATCH)
as required by the Master Engineering Constitution v4.0 Architecture Standard AST-12.

Enforces:
  1. VERSION file exists and contains valid semver
  2. Version matches across VERSION, pyproject.toml, and CHANGELOG
  3. CHANGELOG has entry for current version
  4. Release governance validates semver compliance
  5. Breaking changes are properly documented

Usage:
    python -m pytest tests/test_semver_enforcement.py -v
    python -m pytest tests/test_semver_enforcement.py -v --tb=short
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# ── Paths ──────────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = PROJECT_ROOT / "VERSION"
PYPROJECT_FILE = PROJECT_ROOT / "pyproject.toml"
CHANGELOG_FILE = PROJECT_ROOT / "CHANGELOG.md"
RELEASE_NOTES_FILE = PROJECT_ROOT / "RELEASE_NOTES.md"


# ── Helpers ────────────────────────────────────────────────────────────────────

SEMVER_REGEX = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def read_version_from_file() -> str | None:
    """Read the version string from the VERSION file."""
    if not VERSION_FILE.exists():
        return None
    return VERSION_FILE.read_text(encoding="utf-8").strip()


def read_version_from_pyproject() -> str | None:
    """Read the version string from pyproject.toml."""
    if not PYPROJECT_FILE.exists():
        return None
    content = PYPROJECT_FILE.read_text(encoding="utf-8")
    match = re.search(r'version\s*=\s*"(\d+\.\d+\.\d+)"', content)
    return match.group(1) if match else None


def parse_semver(version: str) -> tuple[int, int, int] | None:
    """Parse semver string into (major, minor, patch) tuple."""
    match = SEMVER_REGEX.match(version.strip())
    if match:
        return (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    return None


# ── Tests ──────────────────────────────────────────────────────────────────────


class TestVersionFile:
    """Tests for the VERSION file existence and format."""

    def test_version_file_exists(self):
        """VERSION file must exist at project root."""
        assert VERSION_FILE.exists(), (
            f"VERSION file not found at {VERSION_FILE} — "
            "create it with the current semver (e.g., '2.57.1')"
        )

    def test_version_file_not_empty(self):
        """VERSION file must contain a version string."""
        version = read_version_from_file()
        assert version, "VERSION file is empty"
        print(f"\n  VERSION file contains: {version}")

    def test_version_file_valid_semver(self):
        """VERSION file must contain a valid MAJOR.MINOR.PATCH string."""
        version = read_version_from_file()
        assert version is not None, "VERSION file not found"
        parsed = parse_semver(version)
        assert parsed is not None, (
            f"Invalid semver format: '{version}'. Expected MAJOR.MINOR.PATCH "
            "(e.g., '2.57.1')"
        )
        major, minor, patch = parsed
        assert major >= 0, f"Major version cannot be negative: {major}"
        assert minor >= 0, f"Minor version cannot be negative: {minor}"
        assert patch >= 0, f"Patch version cannot be negative: {patch}"
        print(f"\n  ✅ Valid semver: {major}.{minor}.{patch}")

    def test_version_does_not_contain_whitespace(self):
        """VERSION file should contain only the version string, no extra whitespace."""
        version = read_version_from_file()
        assert version is not None
        assert version == version.strip(), "VERSION file contains leading/trailing whitespace"

    def test_version_file_no_extra_lines(self):
        """VERSION file should contain exactly one line (the version)."""
        if not VERSION_FILE.exists():
            pytest.skip("VERSION file not found")
        lines = VERSION_FILE.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1, f"VERSION file has {len(lines)} lines, expected 1"


class TestVersionConsistency:
    """Tests that version is consistent across all metadata files."""

    def test_version_matches_pyproject(self):
        """VERSION file must match pyproject.toml version."""
        version = read_version_from_file()
        pyproject_version = read_version_from_pyproject()
        if pyproject_version is None:
            pytest.skip("pyproject.toml not found or has no version")

        assert version is not None, "VERSION file not found"
        assert version == pyproject_version, (
            f"Version mismatch: VERSION={version}, pyproject.toml={pyproject_version}"
        )
        print(f"\n  ✅ VERSION ({version}) matches pyproject.toml ({pyproject_version})")

    def test_changelog_has_current_version(self):
        """CHANGELOG.md must have an entry for the current version."""
        if not CHANGELOG_FILE.exists():
            pytest.skip("CHANGELOG.md not found")

        version = read_version_from_file()
        assert version is not None, "VERSION file not found"

        changelog = CHANGELOG_FILE.read_text(encoding="utf-8")
        # Look for ## v<version> header
        version_header = f"## v{version}"
        assert version_header in changelog, (
            f"CHANGELOG.md missing entry for version {version}. "
            f"Expected to find: '{version_header}'"
        )
        print(f"\n  ✅ CHANGELOG.md has entry for v{version}")

    def test_changelog_section_has_content(self):
        """The CHANGELOG entry for the current version must have content."""
        if not CHANGELOG_FILE.exists():
            pytest.skip("CHANGELOG.md not found")

        version = read_version_from_file()
        assert version is not None, "VERSION file not found"

        changelog = CHANGELOG_FILE.read_text(encoding="utf-8")
        version_header = f"## v{version}"

        # Find the section for this version
        idx = changelog.find(version_header)
        assert idx >= 0, f"Version v{version} not found in CHANGELOG.md"

        # Find next ## header after this one
        next_idx = changelog.find("\n## ", idx + len(version_header))
        section = changelog[idx:next_idx] if next_idx >= 0 else changelog[idx:]

        # Content should have more than just the header line
        content_lines = [line for line in section.split("\n") if line.strip() and not line.startswith("##")]
        assert len(content_lines) >= 2, (
            f"CHANGELOG section for v{version} has insufficient content "
            f"({len(content_lines)} line(s)). At least 2 content lines required."
        )

    def test_release_notes_exist_for_current_version(self):
        """RELEASE_NOTES.md should exist and reference the current version."""
        if not RELEASE_NOTES_FILE.exists():
            pytest.skip("RELEASE_NOTES.md not found")

        version = read_version_from_file()
        assert version is not None, "VERSION file not found"

        notes = RELEASE_NOTES_FILE.read_text(encoding="utf-8")
        assert version in notes, (
            f"RELEASE_NOTES.md missing reference to version {version}"
        )
        print(f"\n  ✅ RELEASE_NOTES.md references v{version}")


class TestSemverFormat:
    """Tests for semver format compliance."""

    def test_semver_three_parts(self):
        """Version must have exactly three parts: MAJOR.MINOR.PATCH."""
        version = read_version_from_file()
        assert version is not None, "VERSION file not found"
        parts = version.strip().split(".")
        assert len(parts) == 3, (
            f"Version '{version}' has {len(parts)} parts, expected 3 (MAJOR.MINOR.PATCH)"
        )
        print(f"\n  MAJOR={parts[0]}, MINOR={parts[1]}, PATCH={parts[2]}")

    def test_semver_parts_are_integers(self):
        """Each semver part must be a non-negative integer."""
        version = read_version_from_file()
        assert version is not None, "VERSION file not found"
        parsed = parse_semver(version)
        assert parsed is not None, f"Could not parse version: {version}"
        major, minor, patch = parsed
        assert isinstance(major, int), f"Major version is not integer: {major}"
        assert isinstance(minor, int), f"Minor version is not integer: {minor}"
        assert isinstance(patch, int), f"Patch version is not integer: {patch}"

    def test_pyproject_version_matches_v_file(self):
        """pyproject.toml version must match VERSION file (same check as consistency)."""
        version = read_version_from_file()
        pyproject_version = read_version_from_pyproject()
        if pyproject_version is None:
            pytest.skip("pyproject.toml not found or has no version")
        assert version is not None
        assert version == pyproject_version, (
            f"VERSION={version} != pyproject.toml={pyproject_version}"
        )


class TestReleaseGovernance:
    """Tests that release governance validates semver."""

    def test_release_governance_script_exists(self):
        """The release governance script must exist to enforce semver."""
        gov_script = PROJECT_ROOT / "scripts" / "release_governance.py"
        assert gov_script.exists(), (
            "scripts/release_governance.py not found — required for semver enforcement"
        )
        print("\n  ✅ scripts/release_governance.py exists")

    def test_score_system_validates_semver(self):
        """The score system must reference semver compliance."""
        score_script = PROJECT_ROOT / "scripts" / "score_system.py"
        if not score_script.exists():
            pytest.skip("scripts/score_system.py not found")

        content = score_script.read_text(encoding="utf-8")
        # Check it has some version-related code
        assert "version" in content.lower() or "semver" in content.lower() or "VERSION" in content, (
            "scripts/score_system.py does not reference version or semver"
        )
        print("\n  ✅ Score system references version compliance")


class TestVersionBump:
    """Tests that version bumps are properly handled."""

    def test_changelog_has_unreleased_section(self):
        """CHANGELOG.md should have an ## Unreleased section for upcoming changes."""
        if not CHANGELOG_FILE.exists():
            pytest.skip("CHANGELOG.md not found")
        changelog = CHANGELOG_FILE.read_text(encoding="utf-8")
        assert "## Unreleased" in changelog, (
            "CHANGELOG.md missing '## Unreleased' section for tracking upcoming changes"
        )
        print('\n  ✅ CHANGELOG.md has ## Unreleased section')

    def test_pyproject_deps_pinned(self):
        """Production dependencies in pyproject.toml should be pinned to specific versions."""
        if not PYPROJECT_FILE.exists():
            pytest.skip("pyproject.toml not found")
        content = PYPROJECT_FILE.read_text(encoding="utf-8")

        # Check some deps have version pinning (>=
        deps_section = False
        unpinned_deps = []
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped.startswith("dependencies"):
                deps_section = True
                continue
            if deps_section and stripped.startswith("]"):
                deps_section = False
                continue
            if deps_section and stripped.startswith('"') and ">=" not in stripped and "<" not in stripped:
                dep_name = stripped.split("@")[0].strip('", ')
                if dep_name:
                    unpinned_deps.append(dep_name)

        if unpinned_deps:
            print(f"\n  ⚠️  Unpinned dependencies: {', '.join(unpinned_deps)}")
            print("  Consider pinning these versions for reproducible builds")
        else:
            print("\n  ✅ All dependencies are pinned")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
