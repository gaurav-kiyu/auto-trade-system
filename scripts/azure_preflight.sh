#!/usr/bin/env bash
set -euo pipefail
: "${OPB_DOMAIN:?Set OPB_DOMAIN to the approved public DNS name}"
command -v docker >/dev/null || { echo "ERROR: docker is required"; exit 1; }
docker compose version >/dev/null || { echo "ERROR: docker compose plugin is required"; exit 1; }
if [ "${OPBUYING_EXECUTION_MODE:-PAPER}" != "PAPER" ]; then echo "ERROR: preflight must run in PAPER mode" >&2; exit 1; fi
if [ -f .env ]; then chmod 600 .env; else echo "ERROR: .env is required outside source control" >&2; exit 1; fi
docker compose -f docker-compose.yml -f deploy/docker-compose.azure.yml config >/dev/null
echo "Azure preflight PASS (PAPER mode; read-only)"
