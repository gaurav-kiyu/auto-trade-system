.PHONY: help install install-dev install-all test test-fast lint typecheck schemas clean dist checksum sbom release

VERSION := $(shell [ -f VERSION ] && cat VERSION || grep -oP '(?<=^version = ")[^"]*' pyproject.toml)

help:
	@echo "Usage: make <target>"
	@echo ""
	@echo "Available targets:"
	@echo "  help          Show this help message"
	@echo "  install       Install production dependencies (pip install -r requirements.txt)"
	@echo "  install-dev   Install dev extras (pip install -e \".[dev]\")"
	@echo "  install-all   Install all extras (pip install -e \".[dev,broker,dashboard,monitoring,ml]\")"
	@echo "  test          Run full test suite"
	@echo "  test-fast     Run tests excluding slow marker"
	@echo "  lint          Run ruff check"
	@echo "  typecheck     Run mypy"
	@echo "  schemas       Regenerate JSON config schemas from defaults"
	@echo "  clean         Remove all build artifacts, caches, logs, and temp files"
	@echo "  dist          Create release tarball (version: $(VERSION))"
	@echo "  checksum      Generate SHA256 checksum of the dist tarball"
	@echo "  release       Run clean, test, lint, typecheck, dist, checksum in sequence"

install:
	pip install -r requirements.txt

install-dev:
	pip install -e ".[dev]"

install-all:
	pip install -e ".[dev,broker,dashboard,monitoring,ml]"

test:
	python -m pytest tests/ -v --tb=short -q

test-fast:
	python -m pytest tests/ -v --tb=short -q -k "not slow"

lint:
	ruff check .

typecheck:
	mypy .

schemas:
	python scripts/generate_config_schemas.py

clean:
	rm -rf __pycache__
	rm -rf .pytest_cache
	rm -rf .mypy_cache
	rm -rf .ruff_cache
	rm -rf .hypothesis
	rm -rf htmlcov
	rm -rf build
	rm -rf dist
	rm -rf *.egg-info
	find . -type f -name '*.pyc' -delete
	find . -type f -name '*.pyo' -delete
	find . -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name '.ipynb_checkpoints' -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.db' -delete
	rm -rf logs/
	rm -f .coverage
	rm -f coverage.xml

dist:
	tar czf ../opbuying-$(VERSION).tar.gz \
		--exclude='.git' \
		--exclude='__pycache__' \
		--exclude='*.pyc' \
		--exclude='.pytest_cache' \
		--exclude='.venv' \
		--exclude='venv' \
		--exclude='logs' \
		--exclude='*.db' \
		--exclude='.env' \
		--exclude='config.json' \
		--exclude='config.local.json' \
		--exclude='models/*' \
		--exclude='.mypy_cache' \
		--exclude='.ruff_cache' \
		--exclude='.hypothesis' \
		--exclude='htmlcov' \
		.

checksum:
	sha256sum ../opbuying-$(VERSION).tar.gz > ../opbuying-$(VERSION).tar.gz.sha256
	@echo "SHA256 checksum written to ../opbuying-$(VERSION).tar.gz.sha256"

sbom:
	@echo "Generating SBOM via pip freeze ..."
	pip freeze > ../opbuying-$(VERSION)-requirements.txt
	@echo "SBOM written to ../opbuying-$(VERSION)-requirements.txt"
	@echo "For CycloneDX format: pip install cyclonedx-bom && cyclonedx-py > ../opbuying-$(VERSION).cdx.json"

release: clean schemas test lint typecheck dist checksum sbom
	@echo "Release $(VERSION) complete: ../opbuying-$(VERSION).tar.gz"
