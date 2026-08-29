# MANDATORY AGENT GOVERNANCE & ENGINEERING CONSTITUTION
## PRODUCTION CHANGE & DEEP REGRESSION GOVERNANCE (OPB-REGRESSION-GOVERNANCE-001)

> **NO CHANGE WITHOUT PRE-GUARD.**
> **NO COMPLETION WITHOUT POST-GUARD.**
> **NO CLAIM WITHOUT EMPIRICAL EVIDENCE.**
> **NO SHARED-COMPONENT CHANGE WITHOUT CONSUMER REGRESSION.**
> **NO THEME CHANGE WITHOUT SCREEN × THEME REGRESSION.**
> **NO RESPONSIVE CHANGE WITHOUT WEB + MOBILE REGRESSION.**
> **NO UI CHANGE MAY REMOVE EXISTING FUNCTIONALITY.**
> **NO "DONE" BASED ON ASSUMPTION.**

---

### 1. The 10 Invariant Laws of Production Changes
1. **Preserve Existing Functionality**: No refactor, redesign, or cleanup may remove, disable, or regress existing controls, icons, toggles, keyboard shortcuts, or accessibility features.
2. **Pre-Guard Mandatory**: Before touching any file, generate a Pre-Guard analysis in `docs/engineering/pre-guard/<id>.md`.
3. **RCA First**: Never patch a symptom in isolation. Identify the architectural root cause and all downstream consumers.
4. **Blast Radius Analysis**: Classify impact (P0 Critical, P1 High, P2 Medium, P3 Low) and run full dependency regression across consumers.
5. **Multi-Theme Parity**: Every visual and interactive change must be verified across all 9 supported themes.
6. **Responsive Parity**: Every interactive control must work seamlessly across Desktop (1440/1280/1024), Tablet (768), and Mobile (375/390/412/430).
7. **Post-Guard Mandatory**: Document actual impact, verified test results, and empirical evidence in `docs/engineering/post-guard/<id>.md`.
8. **CSP Compliance**: 100% nonce-safe event listeners (zero inline `onclick`/`onchange`).
9. **Git & Remote Verification**: Verify `local HEAD == origin/main == AWS deployment`.
10. **Empirical Evidence Required**: Only reproducible test logs and validated telemetry count as proof of completion.
