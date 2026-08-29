"""Regression tests: every CI workflow + docker-compose YAML file must parse.

Guards against recurrence of the CI/compose syntax bugs fixed in v2.57.1:
  - `.github/workflows/ci.yml` and `realestate-ci.yml` had un-indented
    ``python -c`` blocks inside YAML block scalars, which silently broke
    GitHub Actions parsing.
  - `docker-compose.yml` had a healthcheck flow-sequence missing commas.

If any of these files fails ``yaml.safe_load``, CI/compose would break at
deploy time — this test catches that at test time instead.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
GITHUB_DIR = PROJECT_ROOT / ".github"
WORKFLOW_DIR = GITHUB_DIR / "workflows"


def _all_yaml_files() -> list[Path]:
    """Every deployment YAML: workflows/*, .github root configs, docker-compose*.

    Covers .github/workflows/*.yml + *.yaml, .github/*.yml (e.g.
    dependabot.yml) and every docker-compose*.yml, deduped.
    """
    seen: dict[str, Path] = {}
    for pattern in ("*.yml", "*.yaml"):
        for path in WORKFLOW_DIR.glob(pattern):
            seen[str(path)] = path
        for path in GITHUB_DIR.glob(pattern):
            seen[str(path)] = path
    for path in sorted(PROJECT_ROOT.glob("docker-compose*.yml")):
        seen[str(path)] = path
    return [seen[key] for key in sorted(seen)]


YAML_FILES = _all_yaml_files()


def _rel(path: Path) -> str:
    """Path relative to project root, for readable failure messages."""
    return str(path.relative_to(PROJECT_ROOT))


@pytest.mark.parametrize("path", YAML_FILES, ids=_rel)
def test_yaml_parses(path: Path) -> None:
    """Workflow/compose YAML must be syntactically valid YAML."""
    assert path.is_file(), f"Missing YAML file: {_rel(path)}"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        pytest.fail(f"Invalid YAML in {_rel(path)}:\n{exc}")
    assert data is not None, f"{_rel(path)} is empty or comment-only"


class TestYamlCoverage:
    """The guard must actually cover the deployment YAML files."""

    def test_workflow_files_found(self) -> None:
        workflow_names = {p.name for p in YAML_FILES if ".github" in p.parts}
        for expected in (
            "ci.yml",
            "pr-audit.yml",
            "prod-release.yml",
            "realestate-ci.yml",
            "realestate.yml",
            "weekly-deps.yml",
        ):
            assert expected in workflow_names, f"Expected workflow {expected} to be covered by the YAML guard"

    def test_compose_files_found(self) -> None:
        compose_names = {p.name for p in YAML_FILES if p.name.startswith("docker-compose")}
        for expected in (
            "docker-compose.yml",
            "docker-compose.monitoring.yml",
        ):
            assert expected in compose_names, f"Expected compose file {expected} to be covered by the YAML guard"

    def test_github_root_configs_found(self) -> None:
        """Root-level .github YAML (dependabot.yml) must be covered too."""
        github_root_names = {p.name for p in YAML_FILES if p.parent == GITHUB_DIR}
        assert "dependabot.yml" in github_root_names, "Expected .github/dependabot.yml to be covered by the YAML guard"
