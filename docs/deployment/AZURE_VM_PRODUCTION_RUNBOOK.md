# Azure Production Deployment Runbook — OPB v2.59.0

## Recommended target

Use a dedicated **Azure Linux VM** running Docker Compose for the first production deployment. This preserves the current Compose architecture, gives the trading engine a persistent filesystem, and avoids accidental horizontal scaling of an order-execution process.

Do **not** use Azure Container Apps/Kubernetes autoscaling for the trading worker until distributed execution locking/idempotency has been validated. Multiple active trading workers can duplicate signals/orders.

## Target architecture

`Internet -> Caddy HTTPS reverse proxy -> OPB dashboard (8765, localhost-only)`

`OPB trading worker -> persistent /data volumes -> Azure VM disk`

Secrets are injected from the VM environment/secret store and are **not** stored in the release ZIP.

## Pre-deployment gates

- Full local `pytest -q`: PASS (100%)
- Release candidate: v2.59.0
- Execution mode: start in `PAPER`
- Rotate/revoke the previously exposed Telegram token before enabling notifications.
- Create fresh production secrets; do not reuse secrets committed to any historical artifact.
- Configure a restricted NSG/firewall. Allow 80/443 and restricted SSH only; do not expose 8765, broker, Redis, MongoDB, PostgreSQL, or MySQL publicly.

## VM setup (Ubuntu)

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git docker.io docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
```

Log out/in after adding the user to the docker group.

## Deploy the release

Copy the frozen release package to the VM, extract it, and enter the `opb/` directory. Create the environment file **outside source control**.

```bash
cp .env.example .env
chmod 600 .env
```

Minimum production settings for the first smoke test:

```text
OPBUYING_EXECUTION_MODE=PAPER
OPBUYING_WEB_DASHBOARD_ENABLED=true
OPBUYING_BOT_TOKEN=<rotated-token>
OPBUYING_CHAT_ID=<chat-id>
```

Keep broker credentials unset until paper-mode verification is complete.

Start the Azure stack with the HTTPS reverse proxy (replace `example.com` with the approved DNS name):

```bash
export OPB_DOMAIN=example.com
docker compose build
docker compose -f docker-compose.yml -f deploy/docker-compose.azure.yml up -d
docker compose -f docker-compose.yml -f deploy/docker-compose.azure.yml ps
docker compose -f docker-compose.yml -f deploy/docker-compose.azure.yml logs --tail=200 opb caddy
```

## Smoke test

Run the read-only deployment smoke test from the VM. Confirm health, uptime, diagnostics, metrics, and dashboard availability. Do not perform live orders during deployment verification.

## Production activation

Only after paper-mode verification:

1. Confirm risk limits and capital configuration.
2. Inject broker credentials through the secret mechanism.
3. Change execution mode explicitly and document the approval.
4. Restart the single OPB container.
5. Monitor logs/metrics and broker activity continuously during the first live session.

## Rollback

Keep the previous release ZIP/image available. To roll back, stop the current Compose stack, restore the previous release, and restart. Preserve `/data` volumes unless a database rollback is explicitly required.

## Key safety rule

There must be **one active trading worker** for a broker account unless the execution layer provides a proven distributed lock/idempotency mechanism. Do not enable HPA or multiple replicas merely to improve availability.
