#!/usr/bin/env bash
set -euo pipefail

fail() { echo "AWS PREFLIGHT: FAIL: $*" >&2; exit 1; }
pass() { echo "AWS PREFLIGHT: PASS: $*"; }

command -v docker >/dev/null 2>&1 || fail "Docker is not installed"
docker compose version >/dev/null 2>&1 || fail "Docker Compose plugin is not available"

[[ -n "${OPB_DOMAIN:-}" ]] || fail "OPB_DOMAIN is not set"
[[ "${OPBUYING_EXECUTION_MODE:-PAPER}" == "PAPER" ]] || fail "OPBUYING_EXECUTION_MODE must be PAPER for first deployment"
[[ -f .env ]] || fail ".env is missing"

perm=$(stat -c '%a' .env 2>/dev/null || stat -f '%Lp' .env 2>/dev/null || true)
[[ "$perm" == "600" ]] || fail ".env permissions must be 600 (found ${perm:-unknown})"

for f in docker-compose.yml deploy/docker-compose.aws.yml; do
  [[ -f "$f" ]] || fail "Missing $f"
done

docker compose -f docker-compose.yml -f deploy/docker-compose.aws.yml config >/dev/null
pass "Compose configuration parses successfully"

# Verify the dashboard is not published publicly by the AWS override.
if docker compose -f docker-compose.yml -f deploy/docker-compose.aws.yml config | grep -Eq '(^|[[:space:]])-?[[:space:]]*["'"']?8765:8765'; then
  fail "Dashboard port 8765 appears publicly published"
fi
pass "Dashboard port is not publicly published by the AWS compose overlay"

pass "AWS preflight complete; first deployment must remain PAPER mode"
