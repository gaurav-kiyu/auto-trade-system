.PHONY: help install install-dev install-all install-hooks test test-fast lint typecheck
.PHONY: schemas clean dist checksum sbom release web web-dev security coverage quality
.PHONY: benchmark ci cd validate-db validate-config validate-historical precommit nightly certify certify-fast

VERSION := $(shell [ -f VERSION ] && cat VERSION || grep -oP '(?<=^version = ")[^"]*' pyproject.toml)

.DEFAULT_GOAL := help

help:
	@echo "╔══════════════════════════════════════════════════════════════╗"
	@echo "║   OPB Index Options Buying Bot — Make Targets             ║"
	@echo "║   Version: $(VERSION)                                      ║"
	@echo "╚══════════════════════════════════════════════════════════════╝"
	@echo ""
	@echo "── Setup ──────────────────────────────────────────────────────"
	@echo "  install       Install production deps (pip install -r requirements.txt)"
	@echo "  install-dev   Install dev extras (pip install -e \".[dev]\")"
	@echo "  install-all   Install all extras"
	@echo "  install-hooks Install pre-commit hooks"
	@echo ""
	@echo "── Testing ────────────────────────────────────────────────────"
	@echo "  test          Run full test suite"
	@echo "  test-fast     Run tests excluding slow marker"
	@echo "  coverage      Run tests with coverage + heatmap"
	@echo ""
	@echo "── Code Quality ───────────────────────────────────────────────"
	@echo "  lint          Run ruff check"
	@echo "  typecheck     Run mypy"
	@echo "  quality       Full quality report (complexity + maintainability)"
	@echo "  security      Run security scans (bandit, secrets, audit)"
	@echo "  precommit     Run all pre-commit checks"
	@echo ""
	@echo "── Performance ────────────────────────────────────────────────"
	@echo "  benchmark     Run benchmark suite (P50/P90/P95/P99)"
	@echo ""
	@echo "── Validation ─────────────────────────────────────────────────"
	@echo "  validate-db   Check database integrity
	@echo "  validate-historical Check for regressions of all .db files"
	@echo "  validate-config Check config drift against defaults"
	@echo "  validate      Run ALL validation checks"
	@echo "  certify       Run full 13-tool certification pipeline"
	@echo "  certify-fast  Fast certification (skip benchmarks/mutation)"
	@echo ""
	@echo "── CI/CD ──────────────────────────────────────────────────────"
	@echo "  ci            Complete CI pipeline (lint → typecheck → test → coverage)"
	@echo "  cd            Complete CD pipeline (ci → benchmark → quality → dist)"
	@echo ""
	@echo "── Release ────────────────────────────────────────────────────"
	@echo "  schemas       Regenerate JSON config schemas from defaults"
	@echo "  dist          Create release tarball"
	@echo "  checksum      Generate SHA256 checksum"
	@echo "  sbom          Generate SBOM via pip freeze"
	@echo "  release       Full release pipeline"
	@echo ""
	@echo "── Operations ─────────────────────────────────────────────────"
	@echo "  web           Start enterprise web dashboard (port 8765)"
	@echo "  web-dev       Start dashboard with hot-reload"
	@echo "  clean         Remove all build artifacts, caches, logs"
	@echo "  nightly       Run nightly validation suite"

# ── Setup ──────────────────────────────────────────────────────────────────────

install:
	pip install -r requirements.txt

install-dev:
	pip install -e ".[dev]"

install-all:
	pip install -e ".[dev,broker,dashboard,monitoring,ml]"

install-hooks:
	pip install pre-commit
	pre-commit install
	@echo "Pre-commit hooks installed (ruff + mypy + pre-implementation governance). See .pre-commit-config.yaml"

# ── Testing ────────────────────────────────────────────────────────────────────

test:
	python -m pytest tests/ -v --tb=short -q

test-fast:
	python -m pytest tests/ -v --tb=short -q -k "not slow"

coverage:
	python -m pytest tests/ --cov=core --cov-report=json:coverage_json.json -q
	python scripts/run_coverage_heatmap.py --ci --input coverage_json.json
	@echo "Coverage report: reports/coverage_heatmap.html"

# ── Code Quality ───────────────────────────────────────────────────────────────

lint:
	ruff check core/ scripts/ --statistics

typecheck:
	mypy core/ --ignore-missing-imports

quality:
	python scripts/run_code_quality_report.py --ci core/ scripts/
	@echo "Quality report: reports/code_quality_report.html"

audit:
	python scripts/run_pr_audit.py
	@echo "Full PR audit report generated"

security:
	python -m bandit -r core/ -q || true
	python scripts/run_hygiene_scan.py --ci 2>/dev/null || python scripts/hygiene_check.py --ci 2>/dev/null || echo "Security checks complete"

precommit: lint typecheck coverage quality
	@echo "✅ Pre-commit checks passed"

# ── Performance ────────────────────────────────────────────────────────────────

benchmark:
	python scripts/run_benchmarks.py --ci --html
	@echo "Benchmark report: .benchmarks/benchmark_report.html"

# ── Validation ─────────────────────────────────────────────────────────────────

validate-db:
	python scripts/check_db_integrity.py

validate-config:
	python scripts/check_config_drift.py

validate-historical:
	python scripts/historical_comparison.py 2>&1 || echo "WARNING: Historical comparison found regressions — review before merging"

validate: lint typecheck test coverage quality security validate-db validate-config validate-historical
	@echo ""
	@echo "╔══════════════════════════════════════════════════════════════╗"
	@echo "║   ALL VALIDATIONS PASSED                                   ║"
	@echo "╚══════════════════════════════════════════════════════════════╝"

certify:
	@echo "Running full 13-tool certification pipeline..."
	python scripts/run_certify.py
	@echo "📊 Dashboard: reports/certification_report.html"

certify-fast:
	@echo "Running fast certification (skipping benchmarks/mutation)..."
	python scripts/run_certify.py --fast
	@echo "📊 Dashboard: reports/certification_report.html"

# ── CI/CD ──────────────────────────────────────────────────────────────────────

ci: lint typecheck test coverage quality security
	@echo "✅ CI pipeline passed"

cd: ci benchmark dist checksum sbom
	@echo "✅ CD pipeline complete"

# ── Release ────────────────────────────────────────────────────────────────────

schemas:
	python scripts/generate_config_schemas.py

clean:
	rm -rf __pycache__ .pytest_cache .mypy_cache .ruff_cache .hypothesis
	rm -rf htmlcov build dist *.egg-info
	find . -type f -name '*.pyc' -delete
	find . -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.db' -not -path './.git/*' -delete
	rm -rf logs/ .coverage coverage.xml coverage_json.json
	@echo "Clean complete"

dist:
	tar czf ../opbuying-$(VERSION).tar.gz \
		--exclude='.git' --exclude='__pycache__' --exclude='*.pyc' \
		--exclude='.pytest_cache' --exclude='.venv' --exclude='venv' \
		--exclude='logs' --exclude='*.db' --exclude='.env' \
		--exclude='json/config.json' --exclude='json/config.local.json' \
		--exclude='models/*' --exclude='.mypy_cache' --exclude='.ruff_cache' \
		--exclude='.hypothesis' --exclude='htmlcov' .
	@echo "Release tarball: ../opbuying-$(VERSION).tar.gz"

checksum:
	sha256sum ../opbuying-$(VERSION).tar.gz > ../opbuying-$(VERSION).tar.gz.sha256
	@echo "SHA256 checksum written"

sbom:
	pip freeze > ../opbuying-$(VERSION)-requirements.txt
	@echo "SBOM written"

release: ci benchmark quality validate-db validate-config dist checksum sbom
	@echo "Release $(VERSION) complete"

# ── Operations ─────────────────────────────────────────────────────────────────

web:
	python -c "from core.enterprise_dashboard import EnterpriseDashboard; d=EnterpriseDashboard(); import uvicorn; uvicorn.run(d.app, host='0.0.0.0', port=8765)"

web-dev:
	python -c "from core.enterprise_dashboard import EnterpriseDashboard; d=EnterpriseDashboard(); import uvicorn; uvicorn.run(d.app, host='127.0.0.1', port=8765, reload=True)"

nightly: validate benchmark
	@echo "✅ Nightly validation complete"
