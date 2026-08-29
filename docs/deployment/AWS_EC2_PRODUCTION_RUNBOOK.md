# OPB v2.59.0 — AWS EC2 Production Runbook

## Target architecture

Internet → Route 53 DNS → EC2 Security Group → Caddy (80/443) → OPB (127.0.0.1:8765)

The first production deployment uses a single EC2 instance and a single active OPB trader. Do not enable Kubernetes HPA/canary or multiple trading workers until distributed execution locking/idempotency has been formally validated.

## 1. EC2

- Use a supported Amazon Linux or Ubuntu LTS image.
- Allocate persistent storage for `/data` and keep regular snapshots/backups.
- Assign an Elastic IP if a stable public address is required.
- Enable automatic recovery/monitoring appropriate to the workload.

## 2. Security group

Inbound:

- TCP 80 from `0.0.0.0/0` (HTTP; Caddy uses it for ACME/redirect handling).
- TCP 443 from `0.0.0.0/0` (HTTPS).
- TCP 22 only from the administrator's fixed `/32` or approved corporate CIDR. Prefer SSM Session Manager where available and remove public SSH when practical.

Do NOT expose 8765, 6379, 27017, 5432, 3306, or broker/internal service ports to the Internet.

AWS security groups are stateful virtual firewalls; AWS recommends restricting SSH/RDP sources rather than allowing `0.0.0.0/0`. See the AWS security-group documentation before opening access.

## 3. DNS

Create an A/AAAA record for the chosen production hostname pointing to the EC2 public address/Elastic IP. Wait for DNS propagation before starting Caddy.

## 4. Host setup

Install Docker Engine and the Compose plugin. Create a dedicated deployment directory and ensure only the deployment administrator can read secrets.

## 5. Release

Upload `OPB_PHASE13_RELEASE_CANDIDATE_v11.zip`, extract it, and verify the release checksum. Do not copy `.env` from development.

## 6. Secrets

Create `.env` on the EC2 host with mode `600`. Supply broker/Telegram credentials only through the host secret mechanism or a managed secret store. Never commit them to Git or the release ZIP.

Required first-run setting:

`OPBUYING_EXECUTION_MODE=PAPER`

## 7. Preflight

Run:

`./scripts/aws_preflight.sh`

Then validate the rendered Compose configuration:

`docker compose -f docker-compose.yml -f deploy/docker-compose.aws.yml config`

## 8. Start

Run:

`docker compose -f docker-compose.yml -f deploy/docker-compose.aws.yml up -d --build`

Check:

`docker compose -f docker-compose.yml -f deploy/docker-compose.aws.yml ps`

`docker compose -f docker-compose.yml -f deploy/docker-compose.aws.yml logs --tail=200 opb`

`docker compose -f docker-compose.yml -f deploy/docker-compose.aws.yml logs --tail=200 caddy`

## 9. Smoke test

Use the existing read-only deployment smoke test. Confirm HTTPS, application health, static assets, dashboard navigation, and paper-mode operation. Do not send live broker orders.

## 10. Persistence/restart test

Restart the EC2 host or Docker services and verify that `/data` volumes and the application state survive. Confirm the service comes back automatically.

## 11. Live activation gate

Do not change to `LIVE` until:

- PAPER mode is stable for the agreed observation window.
- HTTPS and health checks are stable.
- persistent data survives restart.
- broker credentials have been rotated/verified.
- the previously exposed Telegram token has been revoked/rotated.
- single-worker trading safety is confirmed.
- a manual production approval is recorded.

## 12. Rollback

Keep the previous known-good release package and Docker image available. On failure, stop the new stack, restore the previous release, and verify health before resuming paper/live operation.
