"""Rich Signal Formatter for Production Quantitative Signals (v5.0 - Institutional Gold Standard).

Implements clean human-readable naming, explicit Risk:Reward to Target 2,
target-specific upside metrics, contextualized stop-loss definitions,
and professional portfolio risk limits.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any


class RichSignalFormatter:
    """Produces clean, institutional-grade HTML emails and Telegram cards for trade signals."""

    @classmethod
    def format_human_friendly_symbol(cls, symbol: str, category: str) -> dict[str, str]:
        """Convert technical exchange contract codes into clean human-readable names."""
        cat_upper = category.upper()
        sym_clean = symbol.strip()

        # Options check (e.g., NIFTY24AUG24500CE, BANKNIFTY24AUG52000PE, etc.)
        opt_match = re.match(r"^([A-Z]+)(\d{2}[A-Z]{3})(\d+)(CE|PE)$", sym_clean, re.IGNORECASE)
        if opt_match:
            underlying, expiry, strike_raw, opt_type = opt_match.groups()
            try:
                strike_formatted = f"{int(strike_raw):,}"
            except Exception:
                strike_formatted = strike_raw
            opt_type_full = "Call Option (CE)" if opt_type.upper() == "CE" else "Put Option (PE)"
            opt_type_short = "Call" if opt_type.upper() == "CE" else "Put"

            return {
                "display_title": f"{underlying} {strike_formatted} {opt_type_short} Option",
                "subject_instrument": f"{underlying} {strike_formatted} {opt_type_short}",
                "contract_code": sym_clean,
                "instrument_type": f"Index {opt_type_full}",
                "is_option": True
            }

        # Fallback for simple option symbols like NIFTY_24500_CE
        if "OPTION" in cat_upper or "0DTE" in cat_upper:
            return {
                "display_title": f"{sym_clean} Option",
                "subject_instrument": sym_clean,
                "contract_code": sym_clean,
                "instrument_type": "Options Contract",
                "is_option": True
            }

        # Equities
        return {
            "display_title": sym_clean,
            "subject_instrument": sym_clean,
            "contract_code": sym_clean,
            "instrument_type": "Equity (EQ)",
            "is_option": False
        }

    @classmethod
    def get_holding_horizon_info(cls, category: str, timestamp_str: str = "") -> dict[str, Any]:
        """Compute holding duration, valid date range, and exit strategy based on category."""
        cat_upper = category.upper()
        now = datetime.now()

        if any(w in cat_upper for w in ("OPTION", "0DTE", "INTRADAY", "INDEX")):
            holding_period = "Intraday — same-day exit"
            valid_from = now.strftime("%d %b %Y, 09:15 IST")
            valid_until = now.strftime("%d %b %Y, 15:15 IST")
            short_horizon = "Intraday"
            horizon_badge = "⚡ INTRADAY"
            horizon_color = "#f59e0b"
            is_intraday = True
        elif any(w in cat_upper for w in ("COMMODITY", "CURRENCY")):
            holding_period = "1 – 3 Trading Sessions"
            valid_from = now.strftime("%d %b %Y, %H:%M IST")
            max_dt = now + timedelta(days=3)
            valid_until = max_dt.strftime("%d %b %Y, 23:30 IST")
            short_horizon = "1–3 Days"
            horizon_badge = "🌐 1–3 DAYS"
            horizon_color = "#38bdf8"
            is_intraday = False
        else: # Equities & Positional Breakouts
            holding_period = "1–5 Trading Days"
            valid_from = now.strftime("%d %b %Y, 09:35 IST")
            max_dt = now + timedelta(days=7) # ~5 trading days
            valid_until = max_dt.strftime("%d %b %Y, 15:30 IST")
            short_horizon = "1–5 Days"
            horizon_badge = "📅 1–5 DAYS"
            horizon_color = "#22c55e"
            is_intraday = False

        return {
            "holding_period": holding_period,
            "valid_from": valid_from,
            "valid_until": valid_until,
            "short_horizon": short_horizon,
            "horizon_badge": horizon_badge,
            "horizon_color": horizon_color,
            "is_intraday": is_intraday
        }

    @classmethod
    def format_market_condition(cls, regime: str, is_buy: bool) -> dict[str, str]:
        """Convert technical regime code to human-friendly market condition."""
        regime_upper = regime.upper()
        if "EXPONENTIAL" in regime_upper or "STRONG" in regime_upper or "MOMENTUM" in regime_upper:
            friendly = "Strong Bullish Momentum" if is_buy else "Strong Bearish Momentum"
        elif "TREND" in regime_upper:
            friendly = "Trending Bullish Market" if is_buy else "Trending Bearish Market"
        elif "BREAKOUT" in regime_upper:
            friendly = "High-Volume Breakout" if is_buy else "High-Volume Breakdown"
        elif "MEAN" in regime_upper or "REVERT" in regime_upper:
            friendly = "Institutional Pullback Setup"
        else:
            friendly = "Bullish Setup" if is_buy else "Bearish Breakdown"

        return {
            "friendly": friendly,
            "raw": regime
        }

    @classmethod
    def build_rich_email_subject(
        cls,
        symbol: str,
        category: str,
        direction: str,
        price: float,
        score: int,
        tier: str,
        target_1: float,
        target_2: float,
    ) -> str:
        """Generate a clean, high-scan inbox subject following the user's preferred hierarchy.

        Example: 🟢 NIFTY 24,500 BUY CE (CALL) | Entry ₹142.50 | Target ₹185.25 | Intraday
        Example: 🔴 BANKNIFTY 51,200 BUY PE (PUT) | Entry ₹230.00 | Target ₹285.00 | Intraday
        Example: 📈 TCS BUY (DELIVERY) | Entry ₹2,268.00 | Target ₹2,358.72 | 1–5 Days
        """
        is_buy = direction.upper() in ("CALL", "BUY")
        cat_upper = category.upper()

        if "OPTION" in cat_upper or "0DTE" in cat_upper or "INDEX" in cat_upper:
            if is_buy:
                action_emoji = "🟢"
                action_name = "BUY CE (CALL)"
            else:
                action_emoji = "🔴"
                action_name = "BUY PE (PUT)"
        else:
            action_emoji = "📈"
            action_name = "BUY (CNC / DELIVERY)"

        human_sym = cls.format_human_friendly_symbol(symbol, category)
        horizon = cls.get_holding_horizon_info(category)

        return f"{action_emoji} {human_sym['subject_instrument']} {action_name} | Entry ₹{price:,.2f} | Target ₹{target_1:,.2f} | {horizon['short_horizon']}"

    @classmethod
    def build_rich_html_email(
        cls,
        symbol: str,
        company_name: str,
        series: str,
        category: str,
        direction: str,
        price: float,
        score: int,
        tier: str,
        regime: str,
        rsi: float,
        adx: float,
        vwap: float,
        stop_loss: float,
        target_1: float,
        target_2: float,
        base_url: str = "",
        signal_id: str = "",
    ) -> str:
        """Generate clean, institutional standard HTML email with clear separation of concerns."""
        from core.notifications.url_resolver import build_action_url, build_chart_url

        is_buy = direction.upper() in ("CALL", "BUY")
        action_title = "STRONG BUY SIGNAL" if is_buy else "STRONG SELL SIGNAL"
        action_color = "#22c55e" if is_buy else "#ef4444"
        action_emoji = "🟢" if is_buy else "🔴"

        sl_pct = abs(round(((stop_loss - price) / price) * 100.0, 1))
        t1_pct = abs(round(((target_1 - price) / price) * 100.0, 1))
        t2_pct = abs(round(((target_2 - price) / price) * 100.0, 1))

        # Risk-to-Reward explicitly measured to Target 2
        risk = abs(price - stop_loss)
        reward_t2 = abs(target_2 - price)
        rr_ratio = round(reward_t2 / risk, 1) if risk > 0 else 2.3

        horizon = cls.get_holding_horizon_info(category)
        human_sym = cls.format_human_friendly_symbol(symbol, category)
        mkt_cond = cls.format_market_condition(regime, is_buy)
        score_label = f"{score}/100 — {tier.title()}"

        tv_chart_url = build_chart_url(symbol)
        cockpit_url = build_action_url("/my-signals", base_url=base_url)

        asset_type_label = "the option position" if human_sym["is_option"] else "the stock position"

        if horizon["is_intraday"]:
            exit_step_1 = f"Book <strong>50% of the position</strong> at Target 1 (<strong>₹{target_1:,.2f}</strong>). For the remaining 50%, move the stop loss to the entry price of <strong>₹{price:,.2f}</strong>."
            exit_step_2 = f"Hold the remaining <strong>50% position</strong> for Target 2 (<strong>₹{target_2:,.2f}</strong>)."
            exit_step_3 = "If the targets or stop loss have not been triggered, exit all remaining positions by <strong>15:15 IST</strong>."
            time_label = "Maximum Exit Time:"
        else:
            exit_step_1 = f"Book <strong>50% of your position</strong> at Target 1 (<strong>₹{target_1:,.2f}</strong>). For the remaining 50%, move the stop loss to the entry price of <strong>₹{price:,.2f}</strong> for a risk-free trade."
            exit_step_2 = f"Hold the remaining <strong>50% position</strong> for Target 2 (<strong>₹{target_2:,.2f}</strong>)."
            exit_step_3 = f"If neither Target 2 nor the stop loss is reached, exit the remaining position by <strong>{horizon['valid_until']}</strong>."
            time_label = "Exit By:"

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{action_title}: {human_sym['display_title']}</title>
</head>
<body style="margin:0;padding:0;background-color:#080b10;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#e2e8f0;line-height:1.6;">
    <table width="100%" border="0" cellspacing="0" cellpadding="0" style="background-color:#080b10;padding:24px 12px;">
        <tr>
            <td align="center">
                <!-- Main Container -->
                <table width="100%" border="0" cellspacing="0" cellpadding="0" style="max-width:620px;background:#0d121c;border:1px solid #1e293b;border-radius:14px;overflow:hidden;box-shadow:0 20px 40px rgba(0,0,0,0.6);">

                    <!-- Header -->
                    <tr>
                        <td style="padding:22px 28px;background:linear-gradient(90deg, #0f172a 0%, #1e3a8a 100%);border-bottom:1px solid #334155;">
                            <div style="font-size:11px;font-weight:700;color:#38bdf8;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px;">🎯 OPB QUANTITATIVE ENGINE</div>
                            <div style="font-size:22px;font-weight:800;color:{action_color};letter-spacing:-0.5px;">
                                {action_emoji} {action_title}
                            </div>
                        </td>
                    </tr>

                    <!-- Instrument Title -->
                    <tr>
                        <td style="padding:24px 28px 12px 28px;">
                            <div style="font-size:26px;font-weight:800;color:#ffffff;line-height:1.2;">{human_sym['display_title']}</div>
                            <div style="font-size:13px;color:#94a3b8;margin-top:4px;">
                                <strong>Contract:</strong> <code>{human_sym['contract_code']}</code> &nbsp;•&nbsp; <strong>Instrument:</strong> {human_sym['instrument_type']}
                            </div>
                        </td>
                    </tr>

                    <!-- 📊 SIGNAL SUMMARY -->
                    <tr>
                        <td style="padding:12px 28px;">
                            <div style="font-size:14px;font-weight:800;color:#38bdf8;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:10px;border-bottom:1px solid #1e293b;padding-bottom:6px;">
                                📊 SIGNAL SUMMARY
                            </div>
                            <div style="font-size:13px;color:#cbd5e1;margin-bottom:12px;">
                                <div><strong>Signal Strength:</strong> <span style="color:#22c55e;font-weight:700;">{score_label}</span></div>
                                <div style="margin-top:2px;"><strong>Market Condition:</strong> <span style="color:#ffffff;font-weight:600;">{mkt_cond['friendly']}</span> <span style="color:#64748b;font-size:11px;">(Model: {mkt_cond['raw']})</span></div>
                            </div>

                            <!-- Trade Levels Table -->
                            <table width="100%" border="0" cellspacing="0" cellpadding="8" style="background:#131a29;border:1px solid #1e293b;border-radius:8px;font-size:13px;color:#e2e8f0;">
                                <tr style="border-bottom:1px solid #1e293b;background:#0f1523;">
                                    <th align="left" style="padding:10px 14px;color:#94a3b8;font-weight:600;font-size:12px;text-transform:uppercase;">Trade Level</th>
                                    <th align="right" style="padding:10px 14px;color:#94a3b8;font-weight:600;font-size:12px;text-transform:uppercase;">Price</th>
                                </tr>
                                <tr style="border-bottom:1px solid #1e293b;">
                                    <td style="padding:10px 14px;font-weight:600;">📌 <strong>Entry Price</strong></td>
                                    <td align="right" style="padding:10px 14px;font-family:monospace;font-weight:800;color:#38bdf8;font-size:14px;">₹{price:,.2f}</td>
                                </tr>
                                <tr style="border-bottom:1px solid #1e293b;">
                                    <td style="padding:10px 14px;font-weight:600;">🛡️ <strong>Stop Loss</strong></td>
                                    <td align="right" style="padding:10px 14px;font-family:monospace;font-weight:800;color:#f87171;font-size:14px;">₹{stop_loss:,.2f} (-{sl_pct}%)</td>
                                </tr>
                                <tr style="border-bottom:1px solid #1e293b;">
                                    <td style="padding:10px 14px;font-weight:600;">🎯 <strong>Target 1</strong></td>
                                    <td align="right" style="padding:10px 14px;font-family:monospace;font-weight:800;color:#4ade80;font-size:14px;">₹{target_1:,.2f} (+{t1_pct}%)</td>
                                </tr>
                                <tr style="border-bottom:1px solid #1e293b;">
                                    <td style="padding:10px 14px;font-weight:600;">🚀 <strong>Target 2</strong></td>
                                    <td align="right" style="padding:10px 14px;font-family:monospace;font-weight:800;color:#22c55e;font-size:14px;">₹{target_2:,.2f} (+{t2_pct}%)</td>
                                </tr>
                                <tr>
                                    <td style="padding:10px 14px;font-weight:600;">⚖️ <strong>Risk : Reward to Target 2</strong></td>
                                    <td align="right" style="padding:10px 14px;font-family:monospace;font-weight:800;color:#facc15;font-size:13px;">1 : {rr_ratio}</td>
                                </tr>
                            </table>
                        </td>
                    </tr>

                    <!-- 📅 TRADE PLAN -->
                    <tr>
                        <td style="padding:12px 28px;">
                            <div style="font-size:14px;font-weight:800;color:#38bdf8;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:10px;border-bottom:1px solid #1e293b;padding-bottom:6px;">
                                📅 TRADE PLAN
                            </div>
                            <div style="background:#131a29;border:1px solid #1e293b;border-radius:8px;padding:14px;font-size:13px;color:#cbd5e1;line-height:1.7;">
                                <div><strong>Expected Holding Period:</strong> <span style="color:#ffffff;font-weight:700;">{horizon['holding_period']}</span></div>
                                <div><strong>Signal Valid From:</strong> <span style="color:#ffffff;">{horizon['valid_from']}</span></div>
                                <div><strong>{time_label}</strong> <span style="color:#f59e0b;font-weight:700;">{horizon['valid_until']}</span></div>
                            </div>
                        </td>
                    </tr>

                    <!-- 🎯 EXIT STRATEGY -->
                    <tr>
                        <td style="padding:12px 28px;">
                            <div style="font-size:14px;font-weight:800;color:#38bdf8;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:10px;border-bottom:1px solid #1e293b;padding-bottom:6px;">
                                🎯 EXIT STRATEGY
                            </div>
                            <div style="background:#131a29;border-left:3px solid #22c55e;border-radius:0 8px 8px 0;padding:14px;font-size:13px;color:#cbd5e1;line-height:1.7;">
                                <div style="margin-bottom:10px;">
                                    <strong style="color:#4ade80;">Step 1 — Target 1: ₹{target_1:,.2f}</strong><br>
                                    {exit_step_1}
                                </div>
                                <div style="margin-bottom:10px;">
                                    <strong style="color:#22c55e;">Step 2 — Target 2: ₹{target_2:,.2f}</strong><br>
                                    {exit_step_2}
                                </div>
                                <div>
                                    <strong style="color:#f59e0b;">Step 3 — End of Trading Session / Max Horizon</strong><br>
                                    {exit_step_3}
                                </div>
                            </div>
                        </td>
                    </tr>

                    <!-- 💡 WHAT THIS SIGNAL MEANS -->
                    <tr>
                        <td style="padding:12px 28px;">
                            <div style="font-size:14px;font-weight:800;color:#38bdf8;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:10px;border-bottom:1px solid #1e293b;padding-bottom:6px;">
                                💡 WHAT THIS SIGNAL MEANS
                            </div>
                            <div style="background:#131a29;border:1px solid #1e293b;border-radius:8px;padding:14px;font-size:13px;color:#cbd5e1;line-height:1.7;">
                                <p style="margin:0 0 8px 0;">Our quantitative model currently identifies the <strong>{human_sym['display_title']}</strong> as a strong bullish setup for a <strong>{horizon['short_horizon'].lower()}</strong> trade.</p>
                                <div><strong>Target 1 Potential:</strong> <span style="color:#4ade80;font-weight:700;">+{t1_pct}%</span></div>
                                <div><strong>Target 2 Potential:</strong> <span style="color:#22c55e;font-weight:700;">+{t2_pct}%</span></div>
                                <div style="margin-top:4px;"><strong>Maximum Planned Loss at Stop Loss:</strong> <span style="color:#f87171;font-weight:700;">-{sl_pct}% of {asset_type_label}</span></div>
                                <div style="font-size:11px;color:#94a3b8;margin-top:2px;">(Actual portfolio impact depends on the allocated position size.)</div>
                            </div>
                        </td>
                    </tr>

                    <!-- ⚡ TAKE ACTION -->
                    <tr>
                        <td style="padding:8px 28px 16px 28px;">
                            <div style="font-size:14px;font-weight:800;color:#38bdf8;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:10px;border-bottom:1px solid #1e293b;padding-bottom:6px;">
                                ⚡ TAKE ACTION
                            </div>
                            <table width="100%" border="0" cellspacing="8" cellpadding="0">
                                <tr>
                                    <td width="50%" align="center">
                                        <a href="{cockpit_url}" style="display:block;background:linear-gradient(135deg, #0284c7 0%, #2563eb 100%);color:#ffffff;text-decoration:none;font-weight:700;font-size:13px;padding:12px 16px;border-radius:8px;text-align:center;">
                                            Execute in Cockpit →
                                        </a>
                                    </td>
                                    <td width="50%" align="center">
                                        <a href="{tv_chart_url}" style="display:block;background:#1e293b;border:1px solid #334155;color:#38bdf8;text-decoration:none;font-weight:700;font-size:13px;padding:12px 16px;border-radius:8px;text-align:center;">
                                            📊 View Live Chart
                                        </a>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>

                    <!-- ⚠️ RISK REMINDER -->
                    <tr>
                        <td style="padding:0 28px 24px 28px;">
                            <div style="font-size:13px;font-weight:800;color:#f59e0b;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;">
                                ⚠️ RISK REMINDER
                            </div>
                            <div style="font-size:11px;color:#94a3b8;line-height:1.6;border-top:1px solid #1e293b;padding-top:8px;">
                                This is a quantitative trading signal and does not guarantee returns.
                                <br><br>
                                Option and equity prices can move rapidly, and actual execution may differ from the indicated prices because of market conditions, liquidity, volatility, and slippage.
                                <br><br>
                                <strong>Position Sizing:</strong> Size the position according to your defined portfolio risk limit. Do not risk more than your predefined percentage of portfolio capital on a single trade.
                            </div>
                        </td>
                    </tr>

                    <!-- Footer CTA -->
                    <tr>
                        <td style="padding:16px 28px;background:#090d16;border-top:1px solid #1e293b;text-align:center;font-size:12px;color:#64748b;">
                            <strong style="color:#94a3b8;">OPB Quantitative Engine</strong> • Automated Strategy v5.0
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>"""

    @classmethod
    def build_rich_telegram_message(
        cls,
        symbol: str,
        category: str,
        direction: str,
        price: float,
        score: int,
        tier: str,
        stop_loss: float,
        target_1: float,
        target_2: float,
        signal_id: str = "",
    ) -> str:
        """Generate a clean, visually structured Telegram HTML card with the exact standardized hierarchy."""
        is_buy = direction.upper() in ("CALL", "BUY")
        cat_upper = category.upper()

        if "OPTION" in cat_upper or "0DTE" in cat_upper or "INDEX" in cat_upper:
            if is_buy:
                action_emoji = "🟢"
                action_text = "🎯 OPTION BUYING: BUY CE (CALL)"
            else:
                action_emoji = "🔴"
                action_text = "🎯 OPTION BUYING: BUY PE (PUT)"
        else:
            action_emoji = "📈"
            action_text = "📈 EQUITY SWING / DELIVERY BUY (CNC)"

        sl_pct = abs(round(((stop_loss - price) / price) * 100.0, 1))
        t1_pct = abs(round(((target_1 - price) / price) * 100.0, 1))
        t2_pct = abs(round(((target_2 - price) / price) * 100.0, 1))

        # Risk-to-Reward explicitly measured to Target 2
        risk = abs(price - stop_loss)
        reward_t2 = abs(target_2 - price)
        rr_ratio = round(reward_t2 / risk, 1) if risk > 0 else 2.3

        horizon = cls.get_holding_horizon_info(category)
        human_sym = cls.format_human_friendly_symbol(symbol, category)

        lines = [
            f"<b>{action_emoji} {action_text}</b>",
            f"<b>{human_sym['display_title']}</b>",
            f"<code>Contract: {human_sym['contract_code']}</code>",
            "━━━━━━━━━━━━━━━━━━━━━",
            "📊 <b>SIGNAL SUMMARY</b>",
            f"• <b>Signal Strength:</b> <code>{score}/100 ({tier})</code>",
            f"• 📌 <b>Entry Price:</b> <code>₹{price:,.2f}</code>",
            f"• 🛡️ <b>Stop Loss:</b> <code>₹{stop_loss:,.2f}</code> (-{sl_pct}%)",
            f"• 🎯 <b>Target 1:</b> <code>₹{target_1:,.2f}</code> (+{t1_pct}%)",
            f"• 🚀 <b>Target 2:</b> <code>₹{target_2:,.2f}</code> (+{t2_pct}%)",
            f"• ⚖️ <b>Risk : Reward to Target 2:</b> <code>1 : {rr_ratio}</code>",
            "━━━━━━━━━━━━━━━━━━━━━",
            "📅 <b>TRADE PLAN</b>",
            f"• <b>Expected Holding:</b> <code>{horizon['holding_period']}</code>",
            f"• <b>Valid From:</b> <code>{horizon['valid_from']}</code>",
            f"• <b>Max Exit Time:</b> <code>{horizon['valid_until']}</code>",
            "━━━━━━━━━━━━━━━━━━━━━",
            "🎯 <b>EXIT STRATEGY</b>",
        ]

        if horizon["is_intraday"]:
            lines.append(f"• <b>Step 1:</b> Book 50% at Target 1 (<code>₹{target_1:,.2f}</code>) & move SL to Entry (<code>₹{price:,.2f}</code>).")
            lines.append(f"• <b>Step 2:</b> Hold remaining 50% for Target 2 (<code>₹{target_2:,.2f}</code>).")
            lines.append("• <b>Step 3:</b> Exit remaining by <b>15:15 IST</b>.")
        else:
            lines.append(f"• <b>Step 1:</b> Book 50% at Target 1 (<code>₹{target_1:,.2f}</code>) & move SL to Entry (<code>₹{price:,.2f}</code>).")
            lines.append(f"• <b>Step 2:</b> Hold remaining 50% for Target 2 (<code>₹{target_2:,.2f}</code>).")
            lines.append(f"• <b>Step 3:</b> Exit remaining by <code>{horizon['valid_until']}</code> if Target 2 is untouched.")

        lines.extend([
            "━━━━━━━━━━━━━━━━━━━━━",
            "⚠️ <i>Position Sizing: Size according to your defined risk budget.</i>",
            "🏛️ <b>OPB Quantitative Engine</b>"
        ])

        return "\n".join(lines)

    @classmethod
    def build_rich_telegram_html(
        cls,
        symbol: str,
        category: str = "INDEX_OPTIONS",
        direction: str = "BUY",
        price: float = 0.0,
        score: int = 80,
        tier: str = "STRONG",
        stop_loss: float = 0.0,
        target_1: float = 0.0,
        target_2: float = 0.0,
        **kwargs: Any,
    ) -> str:
        """Alias for build_rich_telegram_message."""
        return cls.build_rich_telegram_message(
            symbol=symbol,
            category=category,
            direction=direction,
            price=price,
            score=score,
            tier=tier,
            stop_loss=stop_loss,
            target_1=target_1,
            target_2=target_2,
            signal_id=kwargs.get("signal_id", ""),
        )
