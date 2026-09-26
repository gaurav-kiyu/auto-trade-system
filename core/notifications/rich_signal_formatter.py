"""Rich Signal Formatter for Production Quantitative Signals (v5.0 - Institutional Gold Standard).

Implements clean human-readable naming, explicit Risk:Reward to Target 2,
target-specific upside metrics, contextualized stop-loss definitions,
and professional portfolio risk limits.
"""

from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from core.notifications.url_resolver import (
    build_action_url,
    get_external_notification_base_url,
    get_public_base_url,
)

_log = logging.getLogger("RICH_SIGNAL_FORMATTER")


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

        # Futures check (e.g. NIFTY26SEPFUT, RELIANCE26SEPFUT, NIFTY-FUT)
        fut_match = re.match(r"^([A-Z&-]+)(\d{2}[A-Z]{3})FUT$", sym_clean, re.IGNORECASE)
        if fut_match:
            underlying, expiry = fut_match.groups()
            return {
                "display_title": f"{underlying} {expiry} Futures Contract",
                "subject_instrument": f"{underlying} {expiry} Futures",
                "contract_code": sym_clean,
                "instrument_type": "Futures Contract (FUT)",
                "is_option": False,
            }
        if "FUTURES" in cat_upper or sym_clean.endswith(("-FUT", "_FUT", "FUT")):
            return {
                "display_title": f"{sym_clean} Futures",
                "subject_instrument": sym_clean,
                "contract_code": sym_clean,
                "instrument_type": "Futures Contract (FUT)",
                "is_option": False,
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
    def _add_trading_days(cls, start_dt: datetime, num_trading_days: int) -> datetime:
        """Add N trading days skipping Saturdays, Sundays, and statutory exchange holidays."""
        # Standard NSE/BSE statutory holidays (YYYY-MM-DD)
        EXCHANGE_HOLIDAYS = {
            "2026-01-26",  # Republic Day
            "2026-03-03",  # Holi
            "2026-03-27",  # Good Friday
            "2026-04-14",  # Dr. Ambedkar Jayanti
            "2026-05-01",  # Maharashtra Day
            "2026-08-15",  # Independence Day
            "2026-10-02",  # Mahatma Gandhi Jayanti
            "2026-10-20",  # Dussehra
            "2026-11-08",  # Diwali Laxmi Pujan
            "2026-11-10",  # Diwali Balipratipada
            "2026-11-24",  # Gurunanak Jayanti
            "2026-12-25",  # Christmas
        }
        current = start_dt
        added = 0
        while added < num_trading_days:
            current += timedelta(days=1)
            # Skip Saturday (5) and Sunday (6)
            if current.weekday() in (5, 6):
                continue
            # Skip statutory holidays
            if current.strftime("%Y-%m-%d") in EXCHANGE_HOLIDAYS:
                continue
            added += 1
        return current

    @classmethod
    def _format_ist_timestamp(cls, timestamp_str: str | None = None) -> str:
        """Format a timestamp string or current IST time into canonical 'DD Mon YYYY, HH:MM:SS IST'."""
        from core.datetime_ist import now_ist

        if timestamp_str and str(timestamp_str).strip():
            raw = str(timestamp_str).strip()
            if "IST" in raw:
                return raw
            try:
                cleaned = raw.replace("Z", "+00:00")
                parsed = datetime.fromisoformat(cleaned)
                if parsed.tzinfo is not None:
                    ist_tz = timezone(timedelta(hours=5, minutes=30))
                    parsed = parsed.astimezone(ist_tz).replace(tzinfo=None)
                return parsed.strftime("%d %b %Y, %H:%M:%S IST")
            except Exception:
                return raw
        return now_ist().strftime("%d %b %Y, %H:%M:%S IST")

    @classmethod
    def get_holding_horizon_info(cls, category: str, timestamp_str: str = "") -> dict[str, Any]:
        """Compute holding duration, valid date range, and exit strategy based on category."""
        from core.datetime_ist import now_ist
        cat_upper = category.upper()

        sig_dt = None
        if timestamp_str:
            try:
                cleaned_ts = str(timestamp_str).replace("Z", "+00:00")
                parsed_dt = datetime.fromisoformat(cleaned_ts)
                if parsed_dt.tzinfo is not None:
                    ist_tz = timezone(timedelta(hours=5, minutes=30))
                    sig_dt = parsed_dt.astimezone(ist_tz).replace(tzinfo=None)
                else:
                    sig_dt = parsed_dt
            except Exception:
                sig_dt = None
        if sig_dt is None:
            _log.warning(
                "[SIGNAL_INTEGRITY] timestamp_str missing or malformed (%r); falling back to now_ist()",
                timestamp_str,
            )
            sig_dt = now_ist()

        if sig_dt.second > 0:
            valid_from = sig_dt.strftime("%d %b %Y, %H:%M:%S IST")
        else:
            valid_from = sig_dt.strftime("%d %b %Y, %H:%M IST")

        if "FUTURES" in cat_upper:
            holding_period = "Positional Futures — 1 to 5 Trading Days"
            exit_dt = cls._add_trading_days(sig_dt, 5)
            valid_until = exit_dt.strftime("%d %b %Y, 15:30 IST")
            short_horizon = "1–5 Days"
            horizon_badge = "📈 FUTURES"
            horizon_color = "#8b5cf6"
            is_intraday = False
        elif any(w in cat_upper for w in ("OPTION", "0DTE", "INTRADAY", "INDEX", "EXPIRY", "VOLATILITY")):
            holding_period = "Intraday — same-day exit"
            # Intraday positions: if generated during live session before 15:15 IST, exit is today 15:15.
            # If generated after 15:15 IST or on weekend/holiday, roll to next active trading day 15:15.
            is_weekend = sig_dt.weekday() in (5, 6)
            is_after_cutoff = (sig_dt.hour > 15) or (sig_dt.hour == 15 and sig_dt.minute >= 15)
            if is_weekend or is_after_cutoff:
                exit_dt = cls._add_trading_days(sig_dt, 1)
                valid_until = exit_dt.strftime("%d %b %Y, 15:15 IST")
            else:
                valid_until = sig_dt.strftime("%d %b %Y, 15:15 IST")
            short_horizon = "Intraday"
            horizon_badge = "⚡ INTRADAY"
            horizon_color = "#f59e0b"
            is_intraday = True
        elif any(w in cat_upper for w in ("COMMODIT", "MCX")):
            holding_period = "1 – 3 Trading Sessions"
            exit_dt = cls._add_trading_days(sig_dt, 3)
            valid_until = exit_dt.strftime("%d %b %Y, 23:30 IST")
            short_horizon = "1–3 Days"
            horizon_badge = "🌐 1–3 DAYS"
            horizon_color = "#38bdf8"
            is_intraday = False
        elif any(w in cat_upper for w in ("CURRENC", "CDS", "FOREX")):
            holding_period = "1 – 2 Trading Sessions"
            exit_dt = cls._add_trading_days(sig_dt, 2)
            valid_until = exit_dt.strftime("%d %b %Y, 17:00 IST")
            short_horizon = "1–2 Days"
            horizon_badge = "💱 1–2 DAYS"
            horizon_color = "#38bdf8"
            is_intraday = False
        else:  # Equities & Positional Breakouts
            holding_period = "1–5 Trading Days"
            exit_dt = cls._add_trading_days(sig_dt, 5)
            valid_until = exit_dt.strftime("%d %b %Y, 15:30 IST")
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
        timestamp_str: str = "",
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
        horizon = cls.get_holding_horizon_info(category, timestamp_str=timestamp_str)

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
        timestamp_str: str = "",
    ) -> str:
        """Generate clean, institutional standard HTML email with clear separation of concerns."""
        from core.notifications.url_resolver import build_action_url, build_chart_url

        is_buy = direction.upper() in ("CALL", "BUY", "LONG")
        tier_norm = str(tier or "STRONG").strip().upper()
        if tier_norm == "MODERATE":
            action_title = "MODERATE BUY SIGNAL" if is_buy else "MODERATE SELL SIGNAL"
        elif tier_norm == "STRONG":
            action_title = "STRONG BUY SIGNAL" if is_buy else "STRONG SELL SIGNAL"
        elif tier_norm == "WEAK":
            action_title = "WEAK BUY SIGNAL" if is_buy else "WEAK SELL SIGNAL"
        else:
            action_title = "BUY SIGNAL" if is_buy else "SELL SIGNAL"
        action_color = "#22c55e" if is_buy else "#ef4444"
        action_emoji = "🟢" if is_buy else "🔴"

        sl_pct = abs(round(((stop_loss - price) / price) * 100.0, 1)) if price > 0 else 3.0
        t1_pct = abs(round(((target_1 - price) / price) * 100.0, 1)) if price > 0 else 4.0
        t2_pct = abs(round(((target_2 - price) / price) * 100.0, 1)) if price > 0 else 8.0

        sl_sign = "-" if is_buy else "+"
        t1_sign = "+" if is_buy else "-"
        t2_sign = "+" if is_buy else "-"

        # Risk-to-Reward explicitly measured to Target 2
        risk = abs(price - stop_loss)
        reward_t2 = abs(target_2 - price)
        rr_ratio = round(reward_t2 / risk, 1) if risk > 0 else 2.3

        horizon = cls.get_holding_horizon_info(category, timestamp_str=timestamp_str)
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
                                    <td align="right" style="padding:10px 14px;font-family:monospace;font-weight:800;color:#f87171;font-size:14px;">₹{stop_loss:,.2f} ({sl_sign}{sl_pct}%)</td>
                                </tr>
                                <tr style="border-bottom:1px solid #1e293b;">
                                    <td style="padding:10px 14px;font-weight:600;">🎯 <strong>Target 1</strong></td>
                                    <td align="right" style="padding:10px 14px;font-family:monospace;font-weight:800;color:#4ade80;font-size:14px;">₹{target_1:,.2f} ({t1_sign}{t1_pct}%)</td>
                                </tr>
                                <tr style="border-bottom:1px solid #1e293b;">
                                    <td style="padding:10px 14px;font-weight:600;">🚀 <strong>Target 2</strong></td>
                                    <td align="right" style="padding:10px 14px;font-family:monospace;font-weight:800;color:#22c55e;font-size:14px;">₹{target_2:,.2f} ({t2_sign}{t2_pct}%)</td>
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
                                <p style="margin:0 0 8px 0;">Our quantitative model currently identifies the <strong>{human_sym['display_title']}</strong> as a {tier_norm.lower()} {'bullish' if is_buy else 'bearish'} setup for a <strong>{horizon['short_horizon'].lower()}</strong> trade.</p>
                                <div><strong>Target 1 Potential:</strong> <span style="color:#4ade80;font-weight:700;">{t1_sign}{t1_pct}%</span></div>
                                <div><strong>Target 2 Potential:</strong> <span style="color:#22c55e;font-weight:700;">{t2_sign}{t2_pct}%</span></div>
                                <div style="margin-top:4px;"><strong>Maximum Planned Loss at Stop Loss:</strong> <span style="color:#f87171;font-weight:700;">{sl_sign}{sl_pct}% of {asset_type_label}</span></div>
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
        timestamp_str: str = "",
    ) -> str:
        """Generate a clean, visually structured Telegram HTML card with the exact standardized hierarchy."""
        is_buy = direction.upper() in ("CALL", "BUY", "LONG")
        cat_upper = category.upper()

        if "OPTION" in cat_upper or "0DTE" in cat_upper or "INDEX" in cat_upper:
            if is_buy:
                action_emoji = "🟢"
                action_text = "🎯 OPTION BUYING: BUY CE (CALL)"
            else:
                action_emoji = "🔴"
                action_text = "🎯 OPTION BUYING: BUY PE (PUT)"
        elif "FUTURES" in cat_upper:
            if is_buy:
                action_emoji = "📈"
                action_text = "📈 FUTURES BUY / LONG"
            else:
                action_emoji = "📉"
                action_text = "📉 FUTURES SELL / SHORT"
        else:
            if is_buy:
                action_emoji = "📈"
                action_text = "📈 EQUITY SWING / DELIVERY BUY (CNC)"
            else:
                action_emoji = "📉"
                action_text = "📉 EQUITY SHORT / SELL SETUP"

        sl_pct = abs(round(((stop_loss - price) / price) * 100.0, 1)) if price > 0 else 3.0
        t1_pct = abs(round(((target_1 - price) / price) * 100.0, 1)) if price > 0 else 4.0
        t2_pct = abs(round(((target_2 - price) / price) * 100.0, 1)) if price > 0 else 8.0

        sl_sign = "-" if is_buy else "+"
        t1_sign = "+" if is_buy else "-"
        t2_sign = "+" if is_buy else "-"

        # Risk-to-Reward explicitly measured to Target 2
        risk = abs(price - stop_loss)
        reward_t2 = abs(target_2 - price)
        rr_ratio = round(reward_t2 / risk, 1) if risk > 0 else 2.3

        horizon = cls.get_holding_horizon_info(category, timestamp_str=timestamp_str)
        human_sym = cls.format_human_friendly_symbol(symbol, category)

        lines = [
            f"<b>{action_emoji} {action_text}</b>",
            f"<b>{human_sym['display_title']}</b>",
            f"<code>Contract: {human_sym['contract_code']}</code>",
        ]
        if signal_id:
            lines.append(f"<code>ID: {signal_id}</code>")
        lines.extend([
            "━━━━━━━━━━━━━━━━━━━━━",
            "📊 <b>SIGNAL SUMMARY</b>",
            f"• <b>Signal Strength:</b> <code>{score}/100 ({tier})</code>",
            f"• 📌 <b>Entry Price:</b> <code>₹{price:,.2f}</code>",
            f"• 🛡️ <b>Stop Loss:</b> <code>₹{stop_loss:,.2f}</code> ({sl_sign}{sl_pct}%)",
            f"• 🎯 <b>Target 1:</b> <code>₹{target_1:,.2f}</code> ({t1_sign}{t1_pct}%)",
            f"• 🚀 <b>Target 2:</b> <code>₹{target_2:,.2f}</code> ({t2_sign}{t2_pct}%)",
            f"• ⚖️ <b>Risk : Reward to Target 2:</b> <code>1 : {rr_ratio}</code>",
            "━━━━━━━━━━━━━━━━━━━━━",
            "📅 <b>TRADE PLAN</b>",
            f"• <b>Expected Holding:</b> <code>{horizon['holding_period']}</code>",
            f"• <b>Valid From:</b> <code>{horizon['valid_from']}</code>",
            f"• <b>Max Exit Time:</b> <code>{horizon['valid_until']}</code>",
            "━━━━━━━━━━━━━━━━━━━━━",
            "🎯 <b>EXIT STRATEGY</b>",
        ])

        if horizon["is_intraday"]:
            lines.append(f"• <b>Step 1:</b> Book 50% at Target 1 (<code>₹{target_1:,.2f}</code>) & move SL to Entry (<code>₹{price:,.2f}</code>).")
            lines.append(f"• <b>Step 2:</b> Hold remaining 50% for Target 2 (<code>₹{target_2:,.2f}</code>).")
            lines.append("• <b>Step 3:</b> Exit remaining by <b>15:15 IST</b>.")
        else:
            lines.append(f"• <b>Step 1:</b> Book 50% at Target 1 (<code>₹{target_1:,.2f}</code>) & move SL to Entry (<code>₹{price:,.2f}</code>).")
            lines.append(f"• <b>Step 2:</b> Hold remaining 50% for Target 2 (<code>₹{target_2:,.2f}</code>).")
            lines.append(f"• <b>Step 3:</b> Exit remaining by <code>{horizon['valid_until']}</code> if Target 2 is untouched.")

        cockpit_link = build_action_url("/my-signals", base_url=get_external_notification_base_url())
        lines.extend([
            "━━━━━━━━━━━━━━━━━━━━━",
            f"🔗 <b>Cockpit:</b> <a href=\"{cockpit_link}\">Execute in OPB Cockpit →</a>",
            "⚡ <i>PAPER / SIGNAL_ONLY (No live trade executed)</i>",
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
            timestamp_str=kwargs.get("timestamp_str", kwargs.get("timestamp", "")),
        )

    @classmethod
    def build_canonical_notification(
        cls,
        signal: dict[str, Any],
        base_url: str = "",
    ) -> dict[str, Any]:
        """Build standardized canonical notification package for Telegram and Email.

        Returns:
            dict containing:
            - subject: Email subject string
            - telegram_html: Rich Telegram HTML string
            - email_html: Full institutional HTML email body
            - plain_text: Plain text fallback string
            - metadata: Normalized signal attributes dict
        """
        def _get_val(k: str, default: Any = None) -> Any:
            if isinstance(signal, dict):
                v = signal.get(k)
            else:
                v = getattr(signal, k, None)
            return v if v is not None else default

        sym = str(_get_val("symbol") or "UNKNOWN").strip().upper()
        category = str(_get_val("category") or "LARGE_CAP_EQUITY").strip().upper()
        direction = str(_get_val("direction") or "BUY").strip().upper()
        price = float(_get_val("price") or _get_val("entry_price") or 0.0)
        score = int(_get_val("score") if _get_val("score") is not None else 80)
        raw_score = float(_get_val("raw_score") or score)
        from core.tier_engine import classify_tier

        raw_tier = _get_val("tier") or _get_val("strength")
        tier = str(raw_tier if raw_tier else classify_tier(score)).strip().upper()
        if tier == "NONE":
            tier = "IGNORE"
        regime = str(_get_val("regime") or "TRENDING").strip()
        rsi = float(_get_val("rsi") or 50.0)
        adx = float(_get_val("adx") or 25.0)
        vwap = float(_get_val("vwap") or price)
        signal_id = str(_get_val("signal_id") or _get_val("sig_id") or "").strip()
        company_name = str(_get_val("company_name") or sym).strip()
        series = str(_get_val("series") or "EQ").strip()
        strategy = str(_get_val("strategy") or _get_val("strategy_name") or "OPB Quantitative Engine").strip()
        timestamp_str = str(
            _get_val("timestamp") or _get_val("generated_at") or _get_val("signal_ts") or _get_val("time") or ""
        ).strip()

        from core.signal_utils import calculate_directional_levels
        stop_loss, target_1, target_2 = calculate_directional_levels(
            entry_price=price,
            direction=direction,
            stop_loss=_get_val("stop_loss"),
            target_1=_get_val("target_1"),
            target_2=_get_val("target_2"),
        )

        subject = cls.build_rich_email_subject(
            symbol=sym,
            category=category,
            direction=direction,
            price=price,
            score=score,
            tier=tier,
            target_1=target_1,
            target_2=target_2,
            timestamp_str=timestamp_str,
        )

        email_html = cls.build_rich_html_email(
            symbol=sym,
            company_name=company_name,
            series=series,
            category=category,
            direction=direction,
            price=price,
            score=score,
            tier=tier,
            regime=regime,
            rsi=rsi,
            adx=adx,
            vwap=vwap,
            stop_loss=stop_loss,
            target_1=target_1,
            target_2=target_2,
            base_url=base_url,
            signal_id=signal_id,
            timestamp_str=timestamp_str,
        )

        telegram_html = cls.build_rich_telegram_message(
            symbol=sym,
            category=category,
            direction=direction,
            price=price,
            score=score,
            tier=tier,
            stop_loss=stop_loss,
            target_1=target_1,
            target_2=target_2,
            signal_id=signal_id,
            timestamp_str=timestamp_str,
        )

        is_buy = direction in ("CALL", "BUY", "LONG")
        sl_sign = "-" if is_buy else "+"
        t1_sign = "+" if is_buy else "-"
        t2_sign = "+" if is_buy else "-"
        sl_pct = abs(round(((stop_loss - price) / price) * 100.0, 1)) if price > 0 else 3.0
        t1_pct = abs(round(((target_1 - price) / price) * 100.0, 1)) if price > 0 else 4.0
        t2_pct = abs(round(((target_2 - price) / price) * 100.0, 1)) if price > 0 else 8.0

        dir_emoji = "🟢" if is_buy else "🔴"
        tier_emoji = "💎" if tier == "STRONG" else ("🟡" if tier == "MODERATE" else "⚪")
        sep = "─" * 32
        plain_text = (
            f"{sep}\n"
            f"🔔 [OPB QUALIFYING SIGNAL]  {dir_emoji}\n"
            f"{sep}\n"
            f"📌 Symbol   : {sym}\n"
            f"💰 Price    : ₹{price:,.2f}\n"
            f"🧭 Direction: {direction}\n"
            f"💪 Strength : {tier} (Score: {score}/100)\n"
            f"{tier_emoji} Tier     : {tier}\n"
            f"📊 Category : {category}\n"
            f"🎯 Strategy : {strategy}\n"
            f"🛑 Stop Loss: ₹{stop_loss:,.2f} ({sl_sign}{sl_pct}%)\n"
            f"🎯 Target 1 : ₹{target_1:,.2f} ({t1_sign}{t1_pct}%)\n"
            f"🎯 Target 2 : ₹{target_2:,.2f} ({t2_sign}{t2_pct}%)\n"
            f"🆔 Signal ID: {signal_id}\n"
            f"{sep}\n"
            f"⚡ Mode     : PAPER / SIGNAL_ONLY\n"
            f"⚠️  Notification only — zero live trade execution.\n"
            f"{sep}"
        )

        if tier == "STRONG":
            severity_code = "SIGNAL_STRONG"
        elif tier == "MODERATE":
            severity_code = "SIGNAL_MODERATE"
        else:
            severity_code = "INFO"
        notif_id = signal_id or f"SIG-{sym}-{cls._format_ist_timestamp(timestamp_str).replace(' ', '').replace(':', '')[-10:]}"
        resolved_base = (base_url or get_external_notification_base_url()).rstrip("/")
        sig_param = f"&signal_id={html.escape(signal_id, quote=True)}" if signal_id else ""
        primary_url = build_action_url(
            f"/my-signals?symbol={html.escape(sym, quote=True)}&action=paper_trade{sig_param}",
            base_url=resolved_base,
        )
        secondary_url = build_action_url("/signals", base_url=resolved_base)

        in_app_payload = {
            "notification_id": notif_id,
            "notification_type": "TRADING_SIGNAL",
            "severity": severity_code,
            "status": f"{tier} {direction}",
            "category_label": f"SIGNAL • {category}",
            "title": f"{sym} — {tier} {direction} @ ₹{price:,.2f}",
            "subtitle": f"{company_name} ({series}) • Score {score}/100",
            "summary": f"Entry ₹{price:,.2f} | SL ₹{stop_loss:,.2f} ({sl_sign}{sl_pct}%) | T1 ₹{target_1:,.2f} ({t1_sign}{t1_pct}%) | T2 ₹{target_2:,.2f} ({t2_sign}{t2_pct}%)",
            "primary_icon": dir_emoji,
            "severity_badge": f"{tier} SIGNAL ({score}/100)",
            "accent_token": "var(--notification-signal)",
            "key_values": [
                {"label": "Symbol", "value": sym, "mono": True},
                {"label": "Direction", "value": direction, "mono": True},
                {"label": "Entry Price", "value": f"₹{price:,.2f}", "mono": True},
                {"label": "Conviction", "value": f"{score}/100 ({tier})", "mono": True},
                {"label": "Stop Loss", "value": f"₹{stop_loss:,.2f} ({sl_sign}{sl_pct}%)", "mono": True},
                {"label": "Target 1", "value": f"₹{target_1:,.2f} ({t1_sign}{t1_pct}%)", "mono": True},
                {"label": "Target 2", "value": f"₹{target_2:,.2f} ({t2_sign}{t2_pct}%)", "mono": True},
                {"label": "Execution Mode", "value": "PAPER / SIGNAL_ONLY", "mono": True},
            ],
            "primary_action": {"label": "Execute Paper Trade", "url": primary_url},
            "secondary_action": {"label": "Open Signal Radar", "url": secondary_url},
            "timestamp_ist": cls._format_ist_timestamp(timestamp_str),
            "source": strategy,
            "footer_note": "OPB v2.59.4 Canonical Signal Engine • Paper / Signal-Only Mode",
        }

        return {
            "notification_id": notif_id,
            "notification_type": "TRADING_SIGNAL",
            "severity": severity_code,
            "subject": subject,
            "telegram_html": telegram_html,
            "email_html": email_html,
            "plain_text": plain_text,
            "in_app": in_app_payload,
            "metadata": {
                "symbol": sym,
                "category": category,
                "direction": direction,
                "price": price,
                "score": score,
                "raw_score": raw_score,
                "tier": tier,
                "stop_loss": stop_loss,
                "target_1": target_1,
                "target_2": target_2,
                "signal_id": signal_id,
            },
        }

    # ══════════════════════════════════════════════════════════════════════════
    # CANONICAL MULTI-CHANNEL NOTIFICATION DESIGN SYSTEM (ALL EVENT FAMILIES)
    # ══════════════════════════════════════════════════════════════════════════

    NOTIFICATION_SEVERITY_SPECS: dict[str, dict[str, str]] = {
        "INFO": {
            "label": "INFO",
            "icon": "ℹ️",
            "accent": "#38bdf8",
            "accent_bright": "#7dd3fc",
            "badge_bg": "#0c2d48",
            "badge_border": "#0284c7",
            "header_grad": "linear-gradient(135deg, #091e34 0%, #0d121c 100%)",
            "cta_grad": "linear-gradient(135deg, #0284c7 0%, #38bdf8 100%)",
            "cta_shadow": "rgba(56, 189, 248, 0.28)",
            "css_token": "var(--notification-info)",
        },
        "SUCCESS": {
            "label": "SUCCESS",
            "icon": "✅",
            "accent": "#10b981",
            "accent_bright": "#34d399",
            "badge_bg": "#063626",
            "badge_border": "#059669",
            "header_grad": "linear-gradient(135deg, #062f23 0%, #0d121c 100%)",
            "cta_grad": "linear-gradient(135deg, #059669 0%, #10b981 100%)",
            "cta_shadow": "rgba(16, 185, 129, 0.28)",
            "css_token": "var(--notification-success)",
        },
        "WARNING": {
            "label": "WARNING",
            "icon": "⚠️",
            "accent": "#f59e0b",
            "accent_bright": "#fbbf24",
            "badge_bg": "#3b2506",
            "badge_border": "#d97706",
            "header_grad": "linear-gradient(135deg, #332007 0%, #0d121c 100%)",
            "cta_grad": "linear-gradient(135deg, #d97706 0%, #f59e0b 100%)",
            "cta_shadow": "rgba(245, 158, 11, 0.28)",
            "css_token": "var(--notification-warning)",
        },
        "ERROR": {
            "label": "ERROR",
            "icon": "🚨",
            "accent": "#ef4444",
            "accent_bright": "#f87171",
            "badge_bg": "#3b0d11",
            "badge_border": "#dc2626",
            "header_grad": "linear-gradient(135deg, #380d12 0%, #0d121c 100%)",
            "cta_grad": "linear-gradient(135deg, #dc2626 0%, #ef4444 100%)",
            "cta_shadow": "rgba(239, 68, 68, 0.28)",
            "css_token": "var(--notification-danger)",
        },
        "CRITICAL": {
            "label": "CRITICAL",
            "icon": "🛑",
            "accent": "#f43f5e",
            "accent_bright": "#fb7185",
            "badge_bg": "#450a18",
            "badge_border": "#e11d48",
            "header_grad": "linear-gradient(135deg, #420916 0%, #0d121c 100%)",
            "cta_grad": "linear-gradient(135deg, #e11d48 0%, #f43f5e 100%)",
            "cta_shadow": "rgba(244, 63, 94, 0.34)",
            "css_token": "var(--notification-danger)",
        },
        "SIGNAL_MODERATE": {
            "label": "MODERATE SIGNAL",
            "icon": "🟡",
            "accent": "#f59e0b",
            "accent_bright": "#fbbf24",
            "badge_bg": "#3b2506",
            "badge_border": "#d97706",
            "header_grad": "linear-gradient(135deg, #332007 0%, #0d121c 100%)",
            "cta_grad": "linear-gradient(135deg, #d97706 0%, #f59e0b 100%)",
            "cta_shadow": "rgba(245, 158, 11, 0.28)",
            "css_token": "var(--notification-signal)",
        },
        "SIGNAL_STRONG": {
            "label": "STRONG SIGNAL",
            "icon": "💎",
            "accent": "#10b981",
            "accent_bright": "#34d399",
            "badge_bg": "#063626",
            "badge_border": "#059669",
            "header_grad": "linear-gradient(135deg, #062f23 0%, #0d121c 100%)",
            "cta_grad": "linear-gradient(135deg, #059669 0%, #10b981 100%)",
            "cta_shadow": "rgba(16, 185, 129, 0.28)",
            "css_token": "var(--notification-signal)",
        },
        "SECURITY": {
            "label": "SECURITY AUDIT",
            "icon": "🛡️",
            "accent": "#a855f7",
            "accent_bright": "#c084fc",
            "badge_bg": "#2b124c",
            "badge_border": "#9333ea",
            "header_grad": "linear-gradient(135deg, #251042 0%, #0d121c 100%)",
            "cta_grad": "linear-gradient(135deg, #7e22ce 0%, #a855f7 100%)",
            "cta_shadow": "rgba(168, 85, 247, 0.28)",
            "css_token": "var(--notification-warning)",
        },
        "ACTION_REQUIRED": {
            "label": "ACTION REQUIRED",
            "icon": "⚡",
            "accent": "#f59e0b",
            "accent_bright": "#fbbf24",
            "badge_bg": "#3b2506",
            "badge_border": "#d97706",
            "header_grad": "linear-gradient(135deg, #332007 0%, #0d121c 100%)",
            "cta_grad": "linear-gradient(135deg, #059669 0%, #10b981 100%)",
            "cta_shadow": "rgba(16, 185, 129, 0.28)",
            "css_token": "var(--notification-warning)",
        },
    }

    @classmethod
    def normalize_severity(cls, severity: str | None) -> str:
        """Normalize any severity string into one of the 9 canonical OPB severities."""
        if not severity:
            return "INFO"
        raw = str(severity).strip().upper()
        if raw in cls.NOTIFICATION_SEVERITY_SPECS:
            return raw
        aliases = {
            "WARN": "WARNING",
            "DANGER": "ERROR",
            "ERR": "ERROR",
            "FATAL": "CRITICAL",
            "EMERGENCY": "CRITICAL",
            "HIGH": "WARNING",
            "MEDIUM": "INFO",
            "LOW": "INFO",
            "OK": "SUCCESS",
            "COMPLETED": "SUCCESS",
            "STRONG": "SIGNAL_STRONG",
            "MODERATE": "SIGNAL_MODERATE",
            "SIGNAL": "SIGNAL_STRONG",
            "AUTH": "SECURITY",
            "AUDIT": "SECURITY",
            "PENDING": "ACTION_REQUIRED",
            "APPROVAL": "ACTION_REQUIRED",
        }
        return aliases.get(raw, "INFO")

    @classmethod
    def build_canonical_event_notification(
        cls,
        *,
        title: str,
        summary: str,
        notification_type: str = "SYSTEM_EVENT",
        severity: str = "INFO",
        status: str | None = None,
        category_label: str | None = None,
        subtitle: str | None = None,
        primary_icon: str | None = None,
        key_values: list[dict[str, Any] | tuple[str, Any]] | None = None,
        sections: list[dict[str, Any]] | None = None,
        primary_action: dict[str, str] | None = None,
        secondary_action: dict[str, str] | None = None,
        notification_id: str | None = None,
        timestamp_str: str | None = None,
        source: str = "OPB Quantitative Engine",
        footer_note: str | None = None,
        subject_override: str | None = None,
        base_url: str | None = None,
        channel_targets: list[str] | None = None,
    ) -> dict[str, Any]:
        """Build a canonical multi-channel OPB notification (Email HTML, Telegram HTML, Plain Text, In-App).

        Uses the exact Reference B dark institutional design system across all notification families.
        """
        norm_sev = cls.normalize_severity(severity)
        spec = cls.NOTIFICATION_SEVERITY_SPECS[norm_sev]
        ts_ist = cls._format_ist_timestamp(timestamp_str)
        resolved_base = (base_url or get_external_notification_base_url()).rstrip("/")

        import hashlib
        if not notification_id:
            digest = hashlib.sha256(f"{notification_type}:{title}:{ts_ist}".encode("utf-8")).hexdigest()[:8].upper()
            notification_id = f"OPB-{digest}"

        icon = primary_icon or spec["icon"]
        cat_label = (category_label or notification_type.replace("_", " ")).strip().upper()
        status_label = (status or spec["label"]).strip().upper()
        sub_text = (subtitle or f"{cat_label} • {ts_ist}").strip()
        foot_text = (
            footer_note
            or "OPB Quantitative Engine v2.59.4 • Institutional Multi-Asset Cockpit • Paper / Signal-Only Governance"
        )
        targets = channel_targets or ["email", "telegram", "in_app"]

        # Normalize key_values into list of dicts: {"label": str, "value": str, "mono": bool, "accent": str|None}
        norm_kvs: list[dict[str, Any]] = []
        for item in key_values or []:
            if isinstance(item, (tuple, list)) and len(item) >= 2:
                norm_kvs.append({
                    "label": str(item[0]),
                    "value": str(item[1]),
                    "mono": True,
                    "accent": item[2] if len(item) > 2 else None,
                })
            elif isinstance(item, dict):
                norm_kvs.append({
                    "label": str(item.get("label") or item.get("key") or ""),
                    "value": str(item.get("value") if item.get("value") is not None else ""),
                    "mono": bool(item.get("mono", True)),
                    "accent": item.get("accent"),
                })

        # Normalize actions with canonical public base_url via url_resolver
        def _norm_action(act: dict[str, str] | None) -> dict[str, str] | None:
            if not act or not act.get("label"):
                return None
            raw_url = str(act.get("url") or "/").strip()
            if raw_url.startswith("/"):
                full_url = build_action_url(raw_url, base_url=resolved_base)
            elif not raw_url.startswith(("http://", "https://")):
                full_url = build_action_url(f"/{raw_url.lstrip('/')}", base_url=resolved_base)
            else:
                import urllib.parse
                parsed = urllib.parse.urlparse(raw_url)
                host = (parsed.hostname or "").lower()
                if host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"} or host.endswith(".localhost") or "nip.io" in host:
                    path_and_query = parsed.path or "/"
                    if parsed.query:
                        path_and_query = f"{path_and_query}?{parsed.query}"
                    full_url = build_action_url(path_and_query, base_url=get_external_notification_base_url())
                else:
                    full_url = raw_url
            return {
                "label": str(act["label"]).strip(),
                "url": full_url,
            }

        norm_primary = _norm_action(primary_action)
        norm_secondary = _norm_action(secondary_action)
        norm_sections = list(sections or [])

        subject = subject_override or f"{icon} [OPB {spec['label']}] {title}"

        email_html = cls._render_canonical_event_email_html(
            notification_id=notification_id,
            notification_type=notification_type,
            severity=norm_sev,
            spec=spec,
            status_label=status_label,
            category_label=cat_label,
            title=title,
            subtitle=sub_text,
            summary=summary,
            primary_icon=icon,
            key_values=norm_kvs,
            sections=norm_sections,
            primary_action=norm_primary,
            secondary_action=norm_secondary,
            timestamp_ist=ts_ist,
            source=source,
            footer_note=foot_text,
        )

        telegram_html = cls._render_canonical_event_telegram_html(
            notification_id=notification_id,
            severity=norm_sev,
            spec=spec,
            status_label=status_label,
            category_label=cat_label,
            title=title,
            subtitle=sub_text,
            summary=summary,
            primary_icon=icon,
            key_values=norm_kvs,
            sections=norm_sections,
            primary_action=norm_primary,
            secondary_action=norm_secondary,
            timestamp_ist=ts_ist,
            source=source,
        )

        plain_text = cls._render_canonical_event_plain_text(
            notification_id=notification_id,
            severity=norm_sev,
            spec=spec,
            status_label=status_label,
            category_label=cat_label,
            title=title,
            subtitle=sub_text,
            summary=summary,
            key_values=norm_kvs,
            sections=norm_sections,
            primary_action=norm_primary,
            secondary_action=norm_secondary,
            timestamp_ist=ts_ist,
            source=source,
            footer_note=foot_text,
        )

        in_app = {
            "notification_id": notification_id,
            "notification_type": notification_type,
            "severity": norm_sev,
            "status": status_label,
            "category_label": cat_label,
            "title": title,
            "subtitle": sub_text,
            "summary": summary,
            "primary_icon": icon,
            "severity_badge": spec["label"],
            "accent_token": spec["css_token"],
            "accent_hex": spec["accent"],
            "key_values": norm_kvs,
            "sections": norm_sections,
            "primary_action": norm_primary,
            "secondary_action": norm_secondary,
            "timestamp_ist": ts_ist,
            "source": source,
            "channel_targets": targets,
            "footer_note": foot_text,
        }

        return {
            "notification_id": notification_id,
            "notification_type": notification_type,
            "severity": norm_sev,
            "status": status_label,
            "category_label": cat_label,
            "title": title,
            "subtitle": sub_text,
            "summary": summary,
            "primary_icon": icon,
            "key_values": norm_kvs,
            "sections": norm_sections,
            "primary_action": norm_primary,
            "secondary_action": norm_secondary,
            "timestamp_ist": ts_ist,
            "source": source,
            "channel_targets": targets,
            "footer_note": foot_text,
            "subject": subject,
            "email_html": email_html,
            "telegram_html": telegram_html,
            "plain_text": plain_text,
            "in_app": in_app,
        }

    @classmethod
    def _render_canonical_event_email_html(
        cls,
        *,
        notification_id: str,
        notification_type: str,
        severity: str,
        spec: dict[str, str],
        status_label: str,
        category_label: str,
        title: str,
        subtitle: str,
        summary: str,
        primary_icon: str,
        key_values: list[dict[str, Any]],
        sections: list[dict[str, Any]],
        primary_action: dict[str, str] | None,
        secondary_action: dict[str, str] | None,
        timestamp_ist: str,
        source: str,
        footer_note: str,
    ) -> str:
        """Render the canonical OPB dark institutional HTML email shell (Reference B standard)."""
        esc_id = html.escape(notification_id)
        esc_cat = html.escape(category_label)
        esc_status = html.escape(status_label)
        esc_title = html.escape(title)
        esc_sub = html.escape(subtitle)
        esc_summary = html.escape(summary).replace("\n", "<br/>")
        esc_icon = html.escape(primary_icon)
        esc_ts = html.escape(timestamp_ist)
        esc_source = html.escape(source)
        esc_footer = html.escape(footer_note)

        accent = spec["accent"]
        accent_bright = spec["accent_bright"]
        badge_bg = spec["badge_bg"]
        badge_border = spec["badge_border"]
        header_grad = spec["header_grad"]
        cta_grad = spec["cta_grad"]
        cta_shadow = spec["cta_shadow"]

        # Build Key-Value table section if key_values present
        kv_block_html = ""
        if key_values:
            kv_rows = []
            for idx, kv in enumerate(key_values):
                lbl = html.escape(str(kv.get("label", "")))
                val = html.escape(str(kv.get("value", "")))
                val_accent = kv.get("accent") or "#f1f5f9"
                font_family = (
                    "'JetBrains Mono','Fira Code',Consolas,monospace"
                    if kv.get("mono", True)
                    else "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif"
                )
                border_bottom = "border-bottom:1px solid #1e293b;" if idx < len(key_values) - 1 else ""
                kv_rows.append(
                    f"<tr>"
                    f"<td style='padding:10px 14px;{border_bottom}font-size:12px;font-weight:600;color:#94a3b8;text-transform:uppercase;letter-spacing:0.6px;width:40%;vertical-align:top;'>{lbl}</td>"
                    f"<td style='padding:10px 14px;{border_bottom}font-size:13px;font-weight:700;color:{val_accent};font-family:{font_family};font-variant-numeric:tabular-nums;text-align:right;vertical-align:top;word-break:break-word;'>{val}</td>"
                    f"</tr>"
                )
            kv_block_html = f"""
          <div style="background:#131a29;border:1px solid #1e293b;border-radius:12px;margin-bottom:16px;overflow:hidden;">
            <div style="padding:10px 14px;background:#0f172a;border-bottom:1px solid #1e293b;font-size:11px;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:1px;">
              📋 TELEMETRY &amp; EVENT DETAILS
            </div>
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
              {''.join(kv_rows)}
            </table>
          </div>"""

        # Build additional structured sections
        sections_html_list = []
        for sec in sections:
            sec_title = html.escape(str(sec.get("title") or "DETAILS"))
            sec_badge = html.escape(str(sec.get("badge") or ""))
            sec_body = html.escape(str(sec.get("body") or "")).replace("\n", "<br/>")
            sec_rows = sec.get("rows") or []
            sec_style = str(sec.get("callout_style") or "").upper()
            sec_border = "#1e293b"
            sec_bg = "#131a29"
            sec_title_color = "#94a3b8"
            if sec_style in cls.NOTIFICATION_SEVERITY_SPECS:
                s_spec = cls.NOTIFICATION_SEVERITY_SPECS[sec_style]
                sec_border = s_spec["badge_border"]
                sec_title_color = s_spec["accent_bright"]

            rows_markup = ""
            if sec_rows:
                r_items = []
                for r_idx, r in enumerate(sec_rows):
                    if isinstance(r, (tuple, list)) and len(r) >= 2:
                        rk, rv = html.escape(str(r[0])), html.escape(str(r[1]))
                    elif isinstance(r, dict):
                        rk = html.escape(str(r.get("label") or r.get("key") or ""))
                        rv = html.escape(str(r.get("value") or ""))
                    else:
                        continue
                    bb = "border-bottom:1px solid #1e293b;" if r_idx < len(sec_rows) - 1 else ""
                    r_items.append(
                        f"<tr>"
                        f"<td style='padding:8px 14px;{bb}font-size:12px;color:#94a3b8;font-weight:600;'>{rk}</td>"
                        f"<td style='padding:8px 14px;{bb}font-size:12px;color:#f8fafc;font-weight:700;font-family:monospace;font-variant-numeric:tabular-nums;text-align:right;'>{rv}</td>"
                        f"</tr>"
                    )
                rows_markup = (
                    f"<table role='presentation' width='100%' cellpadding='0' cellspacing='0' style='border-collapse:collapse;'>"
                    f"{''.join(r_items)}</table>"
                )

            badge_span = (
                f"<span style='float:right;background:{badge_bg};border:1px solid {badge_border};color:{accent_bright};padding:2px 8px;border-radius:4px;font-size:10px;font-weight:800;'>{sec_badge}</span>"
                if sec_badge
                else ""
            )
            body_div = (
                f"<div style='padding:12px 14px;font-size:13px;color:#cbd5e1;line-height:1.6;'>{sec_body}</div>"
                if sec_body
                else ""
            )
            sections_html_list.append(
                f"""
          <div style="background:{sec_bg};border:1px solid {sec_border};border-radius:12px;margin-bottom:16px;overflow:hidden;">
            <div style="padding:10px 14px;background:#0f172a;border-bottom:1px solid #1e293b;font-size:11px;font-weight:700;color:{sec_title_color};text-transform:uppercase;letter-spacing:1px;">
              {sec_title}{badge_span}
            </div>
            {body_div}
            {rows_markup}
          </div>"""
            )

        # Build CTA Buttons block
        cta_html = ""
        if primary_action or secondary_action:
            btn_cells = []
            if primary_action:
                p_lbl = html.escape(primary_action["label"])
                p_url = html.escape(primary_action["url"], quote=True)
                btn_cells.append(
                    f"<td align='center' style='padding:6px;'>"
                    f"<a href='{p_url}' style='display:inline-block;background:{cta_grad};color:#ffffff;text-decoration:none;font-weight:800;font-size:13px;padding:12px 24px;border-radius:8px;letter-spacing:0.4px;box-shadow:0 4px 14px {cta_shadow};'>"
                    f"{p_lbl} &rarr;</a></td>"
                )
            if secondary_action:
                s_lbl = html.escape(secondary_action["label"])
                s_url = html.escape(secondary_action["url"], quote=True)
                btn_cells.append(
                    f"<td align='center' style='padding:6px;'>"
                    f"<a href='{s_url}' style='display:inline-block;background:#1e293b;border:1px solid #334155;color:#38bdf8;text-decoration:none;font-weight:700;font-size:13px;padding:11px 20px;border-radius:8px;letter-spacing:0.3px;'>"
                    f"{s_lbl}</a></td>"
                )
            cta_html = f"""
          <div style="background:#131a29;border:1px solid #1e293b;border-radius:12px;padding:16px;text-align:center;margin-bottom:16px;">
            <table role="presentation" cellpadding="0" cellspacing="0" align="center" style="margin:0 auto;">
              <tr>{''.join(btn_cells)}</tr>
            </table>
          </div>"""

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{esc_title}</title>
</head>
<body style="margin:0;padding:0;background-color:#080b10;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;color:#e2e8f0;-webkit-font-smoothing:antialiased;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#080b10;padding:24px 12px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:640px;background-color:#0d121c;border:1px solid #1e293b;border-radius:16px;overflow:hidden;box-shadow:0 20px 50px rgba(0,0,0,0.6);">

          <!-- 1. TOP BRAND BAR -->
          <tr>
            <td style="background:linear-gradient(90deg,#0f172a 0%,#1e293b 100%);padding:14px 24px;border-bottom:1px solid #1e293b;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td style="font-size:12px;font-weight:800;letter-spacing:1.2px;color:#38bdf8;text-transform:uppercase;">
                    🎯 OPB QUANTITATIVE ENGINE
                  </td>
                  <td align="right" style="font-size:11px;font-weight:700;color:#94a3b8;font-family:'JetBrains Mono',monospace;font-variant-numeric:tabular-nums;">
                    <span style="background:{badge_bg};border:1px solid {badge_border};color:{accent_bright};padding:3px 9px;border-radius:6px;font-size:10px;font-weight:800;letter-spacing:0.6px;">{esc_cat}</span>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- 2. HERO STATUS & TITLE BANNER -->
          <tr>
            <td style="padding:24px 24px 18px 24px;background:{header_grad};border-bottom:1px solid #1e293b;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td valign="top">
                    <div style="margin-bottom:10px;">
                      <span style="display:inline-block;background:{badge_bg};border:1px solid {badge_border};color:{accent_bright};font-size:11px;font-weight:800;padding:4px 10px;border-radius:6px;letter-spacing:0.8px;text-transform:uppercase;">
                        {esc_icon} {esc_status}
                      </span>
                      <span style="display:inline-block;margin-left:6px;background:#1e293b;color:#94a3b8;font-size:11px;font-weight:700;padding:4px 10px;border-radius:6px;font-family:monospace;font-variant-numeric:tabular-nums;">
                        ID: {esc_id}
                      </span>
                    </div>
                    <div style="font-size:22px;font-weight:900;color:#ffffff;letter-spacing:-0.3px;line-height:1.25;">
                      {esc_title}
                    </div>
                    <div style="font-size:12px;color:#94a3b8;margin-top:6px;font-weight:500;">
                      {esc_sub}
                    </div>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- 3. EXECUTIVE SUMMARY & CONTENT CARDS -->
          <tr>
            <td style="padding:20px 24px 8px 24px;">
              <div style="background:#131a29;border-left:4px solid {accent};border-top:1px solid #1e293b;border-right:1px solid #1e293b;border-bottom:1px solid #1e293b;border-radius:10px;padding:16px 18px;margin-bottom:16px;">
                <div style="font-size:10px;font-weight:800;color:{accent_bright};text-transform:uppercase;letter-spacing:1px;margin-bottom:6px;">
                  EXECUTIVE SUMMARY
                </div>
                <div style="font-size:14px;color:#e2e8f0;line-height:1.6;font-weight:500;">
                  {esc_summary}
                </div>
              </div>

              {kv_block_html}
              {''.join(sections_html_list)}
              {cta_html}
            </td>
          </tr>

          <!-- 4. GOVERNANCE FOOTER -->
          <tr>
            <td style="background-color:#090d14;padding:16px 24px;border-top:1px solid #1e293b;font-size:11px;color:#64748b;line-height:1.6;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td style="color:#94a3b8;font-weight:600;">
                    🕒 {esc_ts} &nbsp;|&nbsp; 📡 Source: <span style="color:#cbd5e1;font-family:monospace;">{esc_source}</span>
                  </td>
                  <td align="right" style="font-family:monospace;color:#64748b;font-variant-numeric:tabular-nums;">
                    {esc_id}
                  </td>
                </tr>
              </table>
              <div style="margin-top:8px;padding-top:8px;border-top:1px solid #131a29;color:#475569;font-size:10px;">
                {esc_footer}
              </div>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    @classmethod
    def _render_canonical_event_telegram_html(
        cls,
        *,
        notification_id: str,
        severity: str,
        spec: dict[str, str],
        status_label: str,
        category_label: str,
        title: str,
        subtitle: str,
        summary: str,
        primary_icon: str,
        key_values: list[dict[str, Any]],
        sections: list[dict[str, Any]],
        primary_action: dict[str, str] | None,
        secondary_action: dict[str, str] | None,
        timestamp_ist: str,
        source: str,
    ) -> str:
        """Render the canonical OPB Telegram HTML message with strict HTML entity escaping."""
        esc_id = html.escape(notification_id)
        esc_cat = html.escape(category_label)
        esc_status = html.escape(status_label)
        esc_title = html.escape(title)
        esc_summary = html.escape(summary)
        esc_icon = html.escape(primary_icon)
        esc_ts = html.escape(timestamp_ist)
        esc_source = html.escape(source)

        lines = [
            "🎯 <b>OPB QUANTITATIVE ENGINE</b>",
            f"{esc_icon} <b>[{esc_status}] {esc_cat}</b>",
            f"<b>{esc_title}</b>",
            "━━━━━━━━━━━━━━━━━━━━━",
            f"{esc_summary}",
        ]

        if key_values:
            lines.append("")
            lines.append("📋 <b>Telemetry &amp; Details:</b>")
            for kv in key_values:
                lbl = html.escape(str(kv.get("label", "")))
                val = html.escape(str(kv.get("value", "")))
                lines.append(f"• <b>{lbl}:</b> <code>{val}</code>")

        for sec in sections:
            sec_title = html.escape(str(sec.get("title") or "Details"))
            sec_body = html.escape(str(sec.get("body") or ""))
            sec_rows = sec.get("rows") or []
            lines.append("")
            lines.append(f"🔹 <b>{sec_title}</b>")
            if sec_body:
                lines.append(sec_body)
            for r in sec_rows:
                if isinstance(r, (tuple, list)) and len(r) >= 2:
                    rk, rv = html.escape(str(r[0])), html.escape(str(r[1]))
                elif isinstance(r, dict):
                    rk = html.escape(str(r.get("label") or r.get("key") or ""))
                    rv = html.escape(str(r.get("value") or ""))
                else:
                    continue
                lines.append(f"  • <b>{rk}:</b> <code>{rv}</code>")

        if primary_action or secondary_action:
            lines.append("")
            act_parts = []
            if primary_action:
                p_url = html.escape(primary_action["url"], quote=True)
                p_lbl = html.escape(primary_action["label"])
                act_parts.append(f"🔗 <a href=\"{p_url}\"><b>{p_lbl}</b></a>")
            if secondary_action:
                s_url = html.escape(secondary_action["url"], quote=True)
                s_lbl = html.escape(secondary_action["label"])
                act_parts.append(f"🧭 <a href=\"{s_url}\">{s_lbl}</a>")
            lines.append("  |  ".join(act_parts))

        lines.extend([
            "━━━━━━━━━━━━━━━━━━━━━",
            f"🕒 <i>{esc_ts}</i>  |  📡 <code>{esc_source}</code>",
            f"🆔 <code>{esc_id}</code>",
        ])
        return "\n".join(lines)

    @classmethod
    def _render_canonical_event_plain_text(
        cls,
        *,
        notification_id: str,
        severity: str,
        spec: dict[str, str],
        status_label: str,
        category_label: str,
        title: str,
        subtitle: str,
        summary: str,
        key_values: list[dict[str, Any]],
        sections: list[dict[str, Any]],
        primary_action: dict[str, str] | None,
        secondary_action: dict[str, str] | None,
        timestamp_ist: str,
        source: str,
        footer_note: str,
    ) -> str:
        """Render clean plain-text fallback for any canonical OPB notification."""
        sep = "─" * 44
        lines = [
            sep,
            f"🎯 OPB QUANTITATIVE ENGINE | [{status_label}] {category_label}",
            sep,
            f"{title}",
            f"{subtitle}",
            "",
            f"{summary}",
        ]
        if key_values:
            lines.append("")
            for kv in key_values:
                lines.append(f"• {kv.get('label', '')}: {kv.get('value', '')}")
        for sec in sections:
            lines.append("")
            lines.append(f"[{sec.get('title', 'DETAILS')}]")
            if sec.get("body"):
                lines.append(str(sec["body"]))
            for r in sec.get("rows") or []:
                if isinstance(r, (tuple, list)) and len(r) >= 2:
                    lines.append(f"  - {r[0]}: {r[1]}")
                elif isinstance(r, dict):
                    lines.append(f"  - {r.get('label') or r.get('key')}: {r.get('value')}")
        if primary_action:
            lines.append("")
            lines.append(f"Action — {primary_action['label']}: {primary_action['url']}")
        if secondary_action:
            lines.append(f"Link   — {secondary_action['label']}: {secondary_action['url']}")
        lines.extend([
            sep,
            f"ID: {notification_id} | Time: {timestamp_ist} | Source: {source}",
            f"{footer_note}",
            sep,
        ])
        return "\n".join(lines)

    # ══════════════════════════════════════════════════════════════════════════
    # CANONICAL FACTORY HELPERS FOR ALL 10 REPRESENTATIVE NOTIFICATION FAMILIES
    # ══════════════════════════════════════════════════════════════════════════

    @classmethod
    def build_registration_welcome_notification(
        cls,
        *,
        username: str,
        email: str,
        full_name: str = "",
        role: str = "viewer",
        created_by: str = "self-register",
        status: str = "PENDING_APPROVAL",
        registered_at: str | None = None,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        """Family A1: Canonical User Registration Confirmation / Pending Approval Notification."""
        display_name = full_name.strip() or username.strip()
        return cls.build_canonical_event_notification(
            notification_type="USER_REGISTRATION_WELCOME",
            severity="INFO",
            status=status.replace("_", " "),
            category_label="IDENTITY & ACCESS",
            title=f"Welcome to OPB, {display_name} — Registration Received",
            subtitle=f"Account @{username} is queued for Super Admin verification",
            summary=(
                f"Thank you for registering on the OPB Quantitative Trading Platform. "
                f"Your account ({username}) has been created with the {role} role and status {status}, and is currently "
                f"awaiting administrator authorization. You will receive an activation confirmation as soon as your access is enabled."
            ),
            primary_icon="🛡️",
            key_values=[
                {"label": "Username", "value": username, "mono": True},
                {"label": "Display Name", "value": display_name, "mono": False},
                {"label": "Registered Email", "value": email, "mono": True},
                {"label": "Assigned Role", "value": role, "mono": True, "accent": "#38bdf8"},
                {"label": "Account Status", "value": status, "mono": True, "accent": "#fbbf24"},
                {"label": "Submitted At", "value": cls._format_ist_timestamp(registered_at), "mono": True},
            ],
            sections=[
                {
                    "title": "NEXT STEPS & SECURITY NOTICE",
                    "badge": "GOVERNANCE",
                    "callout_style": "INFO",
                    "body": (
                        "OPB enforces strict institutional access control. Once a Super Admin verifies your registration "
                        "and assigns permitted menus, signal categories, conviction levels, and quotas, "
                        "your cockpit credentials will be activated for Paper / Signal-Only analytics."
                    ),
                }
            ],
            primary_action={"label": "Open OPB Login Portal", "url": "/login"},
            secondary_action={"label": "Platform Documentation", "url": "/help"},
            timestamp_str=registered_at,
            source="OPB Identity & Registration Service",
            subject_override="Welcome to OPB Super-Platform — Authorization Pending",
            base_url=base_url,
        )

    @classmethod
    def build_registration_admin_notification(
        cls,
        *,
        username: str,
        email: str,
        full_name: str = "",
        role: str = "viewer",
        created_by: str = "self-register",
        status: str = "PENDING_APPROVAL",
        registered_at: str | None = None,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        """Family A2: Canonical Admin Alert for New User Registration (Replaces Reference A plain white email)."""
        display_name = full_name.strip() or username.strip() or "—"
        return cls.build_canonical_event_notification(
            notification_type="ADMIN_USER_REGISTRATION_ALERT",
            severity="ACTION_REQUIRED",
            status="PENDING APPROVAL",
            category_label="ADMIN GOVERNANCE • USER ONBOARDING",
            title=f"New OPB User Registration — {username}",
            subtitle="A new user has registered and requires permission review",
            summary=(
                f"A new operator account (@{username}) has registered on the OPB Super-Platform and requires "
                f"Super Admin review in User Authorization & Controls before restricted features become available."
            ),
            primary_icon="👤",
            key_values=[
                {"label": "Username", "value": username, "mono": True, "accent": "#38bdf8"},
                {"label": "Display Name", "value": display_name, "mono": False},
                {"label": "Email", "value": email or "-", "mono": True},
                {"label": "Role", "value": role, "mono": True, "accent": "#c084fc"},
                {"label": "Created By", "value": created_by, "mono": True},
                {"label": "Approval Status", "value": status, "mono": True, "accent": "#fbbf24"},
                {"label": "Registered At", "value": cls._format_ist_timestamp(registered_at), "mono": True},
            ],
            sections=[
                {
                    "title": "USER AUTHORIZATION & CONTROLS WORKFLOW",
                    "badge": "ACTION REQUIRED",
                    "callout_style": "ACTION_REQUIRED",
                    "body": (
                        "Please review the account in User Authorization & Controls and explicitly assign "
                        "the required privileges, permitted menus, signal categories, and conviction tiers "
                        "before the user begins using restricted features."
                    ),
                }
            ],
            primary_action={"label": "Open User Controls", "url": "/admin/users"},
            secondary_action={"label": "Open Security Audit Log", "url": "/security"},
            timestamp_str=registered_at,
            source="OPB Identity & Registration Service",
            subject_override=f"OPB: New User Registration — {username}",
            base_url=base_url,
        )

    @classmethod
    def build_security_notification(
        cls,
        *,
        event_title: str,
        summary: str,
        username: str = "admin",
        actor: str = "SYSTEM",
        ip_address: str = "—",
        role_change: str | None = None,
        severity: str = "SECURITY",
        timestamp_str: str | None = None,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        """Family D: Security / Login / Role / Permission Change Alert."""
        kvs = [
            {"label": "Target Account", "value": username, "mono": True, "accent": "#38bdf8"},
            {"label": "Initiated By", "value": actor, "mono": True},
            {"label": "Source IP", "value": ip_address, "mono": True},
        ]
        if role_change:
            kvs.append({"label": "Permission / Role Delta", "value": role_change, "mono": True, "accent": "#c084fc"})
        return cls.build_canonical_event_notification(
            notification_type="SECURITY_AUDIT_ALERT",
            severity=severity,
            status="SECURITY TELEMETRY",
            category_label="SECURITY & ACCESS CONTROL",
            title=event_title,
            subtitle=f"Account @{username} • Actor: {actor}",
            summary=summary,
            primary_icon="🛡️",
            key_values=kvs,
            primary_action={"label": "Inspect Security Console", "url": "/security"},
            secondary_action={"label": "Manage Users", "url": "/admin/users"},
            timestamp_str=timestamp_str,
            source="OPB Security & RBAC Guard",
            base_url=base_url,
        )

    @classmethod
    def build_password_notification(
        cls,
        *,
        username: str,
        email: str,
        event_subtype: str = "PASSWORD_CHANGED",
        reset_link: str | None = None,
        ip_address: str = "—",
        timestamp_str: str | None = None,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        """Family E: Password Reset / Password Changed Notification."""
        is_reset = "RESET" in event_subtype.upper()
        title = f"Password Reset Requested — @{username}" if is_reset else f"Password Updated — @{username}"
        sev = "ACTION_REQUIRED" if is_reset else "SECURITY"
        status = "RESET REQUESTED" if is_reset else "CREDENTIALS UPDATED"
        summary = (
            f"A password reset was requested for OPB account @{username} ({email}). Use the secure action link below to complete your credential update."
            if is_reset
            else f"The password for OPB account @{username} ({email}) was updated. If you did not authorize this change, contact your Super Admin immediately."
        )
        primary_act = (
            {"label": "Complete Password Reset", "url": reset_link or "/profile"}
            if is_reset
            else {"label": "Review Account Security", "url": "/profile"}
        )
        return cls.build_canonical_event_notification(
            notification_type=event_subtype.upper(),
            severity=sev,
            status=status,
            category_label="CREDENTIAL SECURITY",
            title=title,
            subtitle=f"Account: {email}",
            summary=summary,
            primary_icon="🔐",
            key_values=[
                {"label": "Username", "value": username, "mono": True},
                {"label": "Email", "value": email, "mono": True},
                {"label": "Event Type", "value": status, "mono": True, "accent": "#fbbf24" if is_reset else "#34d399"},
                {"label": "Origin IP", "value": ip_address, "mono": True},
            ],
            primary_action=primary_act,
            secondary_action={"label": "Security Center", "url": "/security"},
            timestamp_str=timestamp_str,
            source="OPB Auth & Credential Service",
            base_url=base_url,
        )

    @classmethod
    def build_paper_trade_notification(
        cls,
        *,
        symbol: str,
        side: str = "BUY",
        quantity: int | float = 1,
        price: float = 0.0,
        status: str = "QUEUED",
        order_id: str = "PAPER-001",
        strategy: str = "OPB Signal Radar",
        timestamp_str: str | None = None,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        """Family F: Paper Trade Queued / Completed Notification."""
        norm_status = status.strip().upper()
        sev = "SUCCESS" if norm_status in ("COMPLETED", "FILLED", "EXECUTED", "QUEUED") else "INFO"
        notional = float(quantity) * float(price)
        return cls.build_canonical_event_notification(
            notification_type="PAPER_TRADE_EXECUTION",
            severity=sev,
            status=f"PAPER {norm_status}",
            category_label="PAPER TRADING ENGINE",
            title=f"Paper Trade {norm_status.title()} — {side.upper()} {symbol.upper()}",
            subtitle=f"Order {order_id} • Simulated Execution Only (Zero Live Capital Risk)",
            summary=(
                f"Simulated paper order {order_id} for {quantity} qty of {symbol.upper()} ({side.upper()}) "
                f"at ₹{price:,.2f} (Notional ₹{notional:,.2f}) is now {norm_status}."
            ),
            primary_icon="🧾",
            key_values=[
                {"label": "Order ID", "value": order_id, "mono": True},
                {"label": "Symbol", "value": symbol.upper(), "mono": True, "accent": "#38bdf8"},
                {"label": "Side / Action", "value": side.upper(), "mono": True, "accent": "#34d399" if side.upper() in ("BUY", "LONG", "CALL") else "#f87171"},
                {"label": "Quantity", "value": f"{quantity}", "mono": True},
                {"label": "Reference Price", "value": f"₹{price:,.2f}", "mono": True},
                {"label": "Simulated Notional", "value": f"₹{notional:,.2f}", "mono": True},
                {"label": "Execution Mode", "value": "PAPER / SIGNAL_ONLY", "mono": True, "accent": "#fbbf24"},
            ],
            primary_action={"label": "View Paper Portfolio", "url": "/paper-ledger"},
            secondary_action={"label": "Open My Signals", "url": "/my-signals"},
            timestamp_str=timestamp_str,
            source=strategy,
            base_url=base_url,
        )

    @classmethod
    def build_system_alert_notification(
        cls,
        *,
        title: str,
        summary: str,
        severity: str = "CRITICAL",
        subsystem: str = "Risk & Kill-Switch Engine",
        metric_label: str = "System State",
        metric_value: str = "HALTED / GUARD ACTIVE",
        action_url: str = "/kill-switch",
        timestamp_str: str | None = None,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        """Family G: System / Risk / Kill-Switch Alert."""
        norm_sev = cls.normalize_severity(severity)
        return cls.build_canonical_event_notification(
            notification_type="SYSTEM_RISK_ALERT",
            severity=norm_sev,
            status=f"{norm_sev} GUARD",
            category_label="RISK & KILL-SWITCH GOVERNANCE",
            title=title,
            subtitle=f"Subsystem: {subsystem}",
            summary=summary,
            primary_icon="🛑" if norm_sev == "CRITICAL" else "⚠️",
            key_values=[
                {"label": "Subsystem", "value": subsystem, "mono": False},
                {"label": metric_label, "value": metric_value, "mono": True, "accent": "#fb7185" if norm_sev == "CRITICAL" else "#fbbf24"},
                {"label": "Severity Tier", "value": norm_sev, "mono": True},
                {"label": "Live Execution", "value": "DISABLED (PAPER / SIGNAL_ONLY)", "mono": True},
            ],
            primary_action={"label": "Open Kill-Switch & Risk Console", "url": action_url},
            secondary_action={"label": "System Observability", "url": "/observability"},
            timestamp_str=timestamp_str,
            source=subsystem,
            base_url=base_url,
        )

    @classmethod
    def build_billing_notification(
        cls,
        *,
        title: str,
        summary: str,
        username: str = "trader",
        plan_name: str = "OPB Pro Institutional",
        amount_inr: float = 0.0,
        payment_reference: str = "UPI-REF-001",
        status: str = "VERIFICATION_PENDING",
        severity: str = "ACTION_REQUIRED",
        timestamp_str: str | None = None,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        """Family H: Billing / UPI / Subscription Notification."""
        return cls.build_canonical_event_notification(
            notification_type="BILLING_SUBSCRIPTION_EVENT",
            severity=severity,
            status=status.replace("_", " "),
            category_label="BILLING & SUBSCRIPTION",
            title=title,
            subtitle=f"Account @{username} • Plan: {plan_name}",
            summary=summary,
            primary_icon="💳",
            key_values=[
                {"label": "Subscriber", "value": username, "mono": True},
                {"label": "Subscription Tier", "value": plan_name, "mono": False, "accent": "#38bdf8"},
                {"label": "Amount (INR)", "value": f"₹{amount_inr:,.2f}", "mono": True, "accent": "#34d399"},
                {"label": "UPI / Payment Ref", "value": payment_reference, "mono": True},
                {"label": "Billing Status", "value": status, "mono": True},
            ],
            primary_action={"label": "Open Subscription & UPI Settings", "url": "/admin/config"},
            secondary_action={"label": "View Account Profile", "url": "/profile"},
            timestamp_str=timestamp_str,
            source="OPB Billing & UPI Settlement Service",
            base_url=base_url,
        )

    @classmethod
    def build_broker_notification(
        cls,
        *,
        broker_name: str,
        status: str = "DISCONNECTED",
        summary: str = "",
        error_code: str = "SESSION_EXPIRED",
        latency_ms: float | None = None,
        severity: str = "ERROR",
        timestamp_str: str | None = None,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        """Family I: Broker Connection / Failure Notification."""
        norm_sev = cls.normalize_severity(severity)
        kvs = [
            {"label": "Broker Adapter", "value": broker_name, "mono": True, "accent": "#38bdf8"},
            {"label": "Connection State", "value": status.upper(), "mono": True, "accent": "#f87171" if norm_sev in ("ERROR", "CRITICAL") else "#34d399"},
            {"label": "Diagnostic Code", "value": error_code, "mono": True},
        ]
        if latency_ms is not None:
            kvs.append({"label": "Heartbeat Latency", "value": f"{latency_ms:.1f} ms", "mono": True})
        return cls.build_canonical_event_notification(
            notification_type="BROKER_CONNECTIVITY_EVENT",
            severity=norm_sev,
            status=f"BROKER {status.upper()}",
            category_label="BROKER & FEED CONNECTIVITY",
            title=f"Broker Adapter {status.title()} — {broker_name}",
            subtitle=f"Diagnostic Code: {error_code}",
            summary=summary or f"Broker adapter {broker_name} transitioned to state {status.upper()} ({error_code}).",
            primary_icon="🔌",
            key_values=kvs,
            primary_action={"label": "Inspect Broker Connectivity", "url": "/observability"},
            secondary_action={"label": "Open Admin Configuration", "url": "/admin/config"},
            timestamp_str=timestamp_str,
            source=f"OPB Broker Gateway ({broker_name})",
            base_url=base_url,
        )

    @classmethod
    def build_delivery_failure_notification(
        cls,
        *,
        failed_channel: str,
        recipient: str,
        error_reason: str,
        retry_count: int = 1,
        dlq_status: str = "QUEUED_FOR_RETRY",
        original_notification_id: str = "OPB-0000",
        severity: str = "WARNING",
        timestamp_str: str | None = None,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        """Family J: Notification Delivery Failure / Retry / DLQ Alert."""
        norm_sev = cls.normalize_severity(severity)
        return cls.build_canonical_event_notification(
            notification_type="NOTIFICATION_DELIVERY_FAILURE",
            severity=norm_sev,
            status=dlq_status.replace("_", " "),
            category_label="NOTIFICATION DISPATCH & DLQ",
            title=f"Channel Delivery Alert — {failed_channel.upper()}",
            subtitle=f"Original Notification {original_notification_id} • Retry #{retry_count}",
            summary=(
                f"Delivery over channel {failed_channel.upper()} to recipient {recipient} encountered a transport error: "
                f"{error_reason}. Current dispatch state: {dlq_status}."
            ),
            primary_icon="📬",
            key_values=[
                {"label": "Failed Channel", "value": failed_channel.upper(), "mono": True, "accent": "#fbbf24"},
                {"label": "Target Recipient", "value": recipient, "mono": True},
                {"label": "Original Event ID", "value": original_notification_id, "mono": True},
                {"label": "Retry Attempt", "value": f"#{retry_count}", "mono": True},
                {"label": "DLQ / Dispatch Status", "value": dlq_status, "mono": True},
                {"label": "Transport Diagnostic", "value": error_reason, "mono": True, "accent": "#f87171"},
            ],
            primary_action={"label": "Inspect Notification Telemetry", "url": "/admin/config"},
            secondary_action={"label": "Open System Logs", "url": "/observability"},
            timestamp_str=timestamp_str,
            source="OPB Multi-Channel Notification Dispatcher",
            base_url=base_url,
        )


