# 🏛️ OPB SUPER-PLATFORM: PHASE 10 SCORE ENGINE INVENTORY

**Audit Standard**: Statistical Scoring Architecture & Component Lineage Audit  
**Auditor**: Independent Senior Quantitative Researcher  

---

## 📋 1. SCORING ENGINE MODULE INVENTORY

| Component | Source File | Implementing Function | Inputs | Point Contribution | Theoretical Max |
| :--- | :--- | :--- | :--- | :---: | :---: |
| **Timeframe Alignment** | `core/pure_index_signal.py` | `compute_index_score()` | `t5`, `t15` trend states | $+20$ if $t_5 == t_{15}$ | 20 |
| **VWAP Conviction** | `core/pure_index_signal.py` | `compute_index_score()` | `price`, `vwap` distance | $+8$ to $+20$ based on % dist | 20 |
| **1m Delta Momentum** | `core/pure_index_signal.py` | `compute_index_score()` | `d1` 10-bar 1m delta | $+15$ if direction aligned | 15 |
| **5m Delta Momentum** | `core/pure_index_signal.py` | `compute_index_score()` | `d5` 3-bar 5m delta | $+10$ if direction aligned | 10 |
| **Volume Surge** | `core/pure_index_signal.py` | `compute_index_score()` | `vol`, `vol_ratio_min` | $+4$ to $+14$ based on ratio excess | 14 |
| **ATR Volatility Floor** | `core/pure_index_signal.py` | `compute_index_score()` | `atr`, `_atr_min` | $+5$ if ATR above floor | 5 |
| **RSI Continuation** | `core/pure_index_signal.py` | `compute_index_score()` | `rsi`, healthy bands | $+8$ if in continuation zone | 8 |
| **Smart Money OI** | `core/pure_index_signal.py` | `compute_index_score()` | `smart` F&O sentiment | $+10$ if aligned | 10 |
| **PCR Alignment** | `core/pure_index_signal.py` | `compute_index_score()` | `pcr`, bullish/bearish thresholds | $+5$ if aligned | 5 |
| **IV Rank Multiplier** | `core/adaptive_signal_score_adjusters.py` | `apply_iv_rank_adjustment()` | `vix`, config | Multiplier $[0.85, 1.15]$ | $\pm 15\%$ |
| **IV Skew Penalty** | `core/adaptive_signal_score_adjusters.py` | `apply_iv_skew_adjustment()` | option chain, spot | $-5$ penalty on extreme put skew | $-5$ |
| **TF Mismatch Soft Penalty**| `core/adaptive_signal.py` | `evaluate_adaptive_signal()` | timeframe mismatch | $-25$ score, conf $\times 0.50$ | $-25$ |
| **Choppy Regime Soft Penalty**| `core/adaptive_signal.py` | `evaluate_adaptive_signal()` | regime classification | $-18$ score, conf $\times 0.60$ | $-18$ |

**Max Theoretical Raw Score**: $20 + 20 + 15 + 10 + 14 + 5 + 8 + 10 + 5 = 107$ (Capped at 100).
