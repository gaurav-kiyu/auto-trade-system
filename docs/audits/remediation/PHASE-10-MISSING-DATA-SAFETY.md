# 🏛️ OPB SUPER-PLATFORM: PHASE 10 MISSING & STALE DATA SAFETY

**Audit Standard**: Fail-Closed Data Integrity Audit  
**Auditor**: Independent Software Forensics Engineer  

---

## 🛑 1. FAIL-CLOSED BEHAVIOR ON DATA CORRUPTION

- **Stale LTP ($>30\text{s}$)**: Pre-Guard fails -> Vetoed to `NO_TRADE`.
- **Missing Option Chain**: IV Skew & PCR skipped gracefully; score cannot reach $\ge 85$ due to missing 15 OI points.
- **Negative / Zero Price**: Immediate schema validation error; signal generation suppressed.
