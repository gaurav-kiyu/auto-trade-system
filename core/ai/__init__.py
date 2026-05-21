"""
AD-KIYU AI Governance Package.

Provides formal model lifecycle management:
  - ModelRegistry: SQLite-backed registry with semver versioning
  - CanaryManager: staged canary rollout (10% → 50% → 100%)
  - RollbackController: drift-triggered automated rollback
  - AIGovernanceBoard: orchestrates all governance policies
"""
