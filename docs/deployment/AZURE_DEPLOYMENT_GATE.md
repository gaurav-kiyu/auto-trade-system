# Azure Deployment Gate — v2.59.0

- [ ] Telegram token revoked/rotated
- [ ] Fresh broker credentials generated/validated
- [ ] Azure VM created in approved region
- [ ] NSG allows only required HTTPS/SSH access
- [ ] Docker installed and enabled
- [ ] `bash scripts/azure_preflight.sh` passes in PAPER mode
- [ ] Release v2.59.0 copied to VM
- [ ] `.env` created outside source control with mode 600
- [ ] `OPBUYING_EXECUTION_MODE=PAPER`
- [ ] Dashboard health verified
- [ ] Read-only smoke test passes
- [ ] Persistent `/data` volumes verified
- [ ] Backup/restore procedure tested
- [ ] Paper-mode session observed successfully
- [ ] Live-mode approval obtained
- [ ] Broker secrets injected only after approval
- [ ] Single active trading worker confirmed
- [ ] Post-deployment monitoring enabled
