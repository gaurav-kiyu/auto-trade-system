# 🏛️ OPB SUPER-PLATFORM: PHASE 11 SIGNAL GOVERNANCE & LIMIT ENGINE AUDIT

**Audit Standard**: Rate Limiting & Multi-Tier Precedence Hierarchy  
**Auditor**: Independent Systems Architect  

---

## 🚦 1. LIMIT PRECEDENCE HIERARCHY

$$\text{GLOBAL CAP} \to \text{ASSET CAP} \to \text{CATEGORY CAP} \to \text{USER TIER CAP} \to \text{DAILY RISK LIMIT}$$

- **Persistence**: Daily counters are backed by SQLite state table `signal_counters` and survive process restarts without resetting prematurely.
- **Midnight Boundary**: Reset occurs strictly at 00:00:00 IST via scheduled worker.
