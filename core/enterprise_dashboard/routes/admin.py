"""Admin control route registration for the Enterprise Dashboard.

Handles: /api/config/* (CRUD), /api/changes/* (change management),
/api/system/kill, /api/system/resume, /api/system/pause, /api/system/resume-entry,
/api/system/self-test.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from fastapi import Depends, Request

from core.enterprise_dashboard.routes.pages import _page_context

_log = logging.getLogger(__name__)


def register_admin_routes(app, dashboard, admin_only, operator_or_admin) -> None:
    @app.post("/api/v1/admin/test-dispatch-signal")
    async def api_test_dispatch_signal(request: Request, user: Any = Depends(dashboard._auth_deps.require_permission("modify_config"))):
        """Dispatch a live test trade signal across Telegram, Email, and DB Signal Tracker."""
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        import requests

        from core.auth.user_signal_permissions import UserPermissionManager
        from core.datetime_ist import now_ist
        from core.notifications.rich_signal_formatter import RichSignalFormatter
        from core.signals.signal_tracker import SignalTracker

        try:
            body = await request.json()
        except Exception:
            body = {}

        cfg = dashboard._cfg
        bot_token = str(body.get("bot_token") or cfg.get("BOT_TOKEN", "")).strip()
        chat_ids_raw = str(body.get("telegram_chat_ids") or cfg.get("CHAT_ID", "")).strip()
        chat_ids = [c.strip() for c in chat_ids_raw.split(",") if c.strip()]

        email_user = str(cfg.get("EMAIL_USER", "")).strip()
        email_pass = str(cfg.get("EMAIL_PASS", "")).strip().replace(" ", "")
        smtp_host = str(cfg.get("EMAIL_SMTP", "smtp.gmail.com")).strip()
        smtp_port = int(cfg.get("EMAIL_PORT", 587))

        email_to_raw = str(body.get("email_recipients") or cfg.get("EMAIL_TO", "")).strip()
        recipients = [r.strip() for r in email_to_raw.split(",") if r.strip() and "@" in r]

        symbol = str(body.get("symbol") or "NIFTY24AUG24500CE").strip().upper()
        company_name = str(body.get("company_name") or f"{symbol} CONTRACT").strip()
        category = str(body.get("category") or "INDEX_OPTIONS").strip().upper()
        direction = str(body.get("direction") or "CALL").strip().upper()
        price = float(body.get("price") or 142.50)
        score = int(body.get("score") or 92)
        tier = str(body.get("tier") or "STRONG").strip().upper()
        regime = str(body.get("regime") or "TRENDING_BULLISH").strip()
        stop_loss = float(body.get("stop_loss") or round(price * 0.85, 2))
        target_1 = float(body.get("target_1") or round(price * 1.25, 2))
        target_2 = float(body.get("target_2") or round(price * 1.50, 2))

        # Format signal
        rich_tg_msg = RichSignalFormatter.build_rich_telegram_html(
            symbol=symbol,
            category=category,
            direction=direction,
            price=price,
            score=score,
            tier=tier,
            stop_loss=stop_loss,
            target_1=target_1,
            target_2=target_2,
        )

        from core.notifications.url_resolver import get_public_base_url
        base_url = get_public_base_url(cfg)

        rich_html_email = RichSignalFormatter.build_rich_html_email(
            symbol=symbol,
            company_name=company_name,
            series="OPTIDX" if "OPTION" in category else "EQ",
            category=category,
            direction=direction,
            price=price,
            score=score,
            tier=tier,
            regime=regime,
            rsi=64.8,
            adx=32.4,
            vwap=price * 0.98,
            stop_loss=stop_loss,
            target_1=target_1,
            target_2=target_2,
            base_url=base_url,
        )

        # Record in SignalTracker
        perm_mgr = UserPermissionManager.get_instance()
        eligible_users = perm_mgr.get_eligible_recipients(category=category, tier=tier, symbol=symbol)
        tracker = SignalTracker.get_instance()
        signal_id = tracker.record_generated_signal({
            "symbol": symbol,
            "company_name": company_name,
            "series": "OPTIDX",
            "direction": direction,
            "price": price,
            "score": score,
            "tier": tier,
            "regime": regime,
            "category": category,
            "stop_loss": stop_loss,
            "target_1": target_1,
            "target_2": target_2,
        }, eligible_users=eligible_users) or "SIG-TEST"

        rich_tg_msg += (
            f"\n\n🆔 <b>Signal ID:</b> <code>{signal_id}</code>\n"
            f"Reply <code>/placed {signal_id}</code> once executed."
        )

        rich_html_email = rich_html_email.replace(
            "</body>",
            f"""<div style="background:#0f172a;border-top:1px solid #334155;padding:14px;text-align:center;font-size:12px;color:#94a3b8;">
                🆔 <b>Institutional Signal ID:</b> <code style="color:#38bdf8;background:#1e293b;padding:2px 6px;border-radius:4px;">{signal_id}</code>
                <br>Reply <code>/placed {signal_id}</code> in Telegram once placed to track fill performance.
            </div></body>"""
        )

        # 1. Dispatch Telegram
        tg_results = []
        if bot_token and chat_ids:
            for cid in chat_ids:
                tg_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                payload = {
                    "chat_id": cid,
                    "text": rich_tg_msg,
                    "parse_mode": "HTML",
                    "reply_markup": {
                        "inline_keyboard": [
                            [
                                *(
                                    [{"text": "⚡ 1-Click Paper Trade", "callback_data": f"paper:{symbol}"}]
                                    + ([{"text": "🚀 1-Click Execute", "callback_data": f"exec:{symbol}"}]
                                       if bool(cfg.get("ENABLE_TELEGRAM_EXECUTE_BUTTON", False))
                                       and str(cfg.get("EXECUTION_MODE", "SIGNAL_ONLY")).upper() in {"AUTO", "PAPER"}
                                       else [])
                                ),
                            ],
                            [
                                {"text": "📊 View Chart", "url": f"https://in.tradingview.com/chart/?symbol=NSE:{symbol}"},
                                {"text": "🏛️ Cockpit Dashboard", "url": f"{base_url}/my-signals"},
                            ]
                        ]
                    }
                }
                try:
                    res = requests.post(tg_url, json=payload, timeout=12)
                    res_j = res.json()
                    tg_results.append({
                        "chat_id": cid,
                        "success": bool(res_j.get("ok")),
                        "detail": res_j.get("result", {}).get("message_id") if res_j.get("ok") else res_j.get("description", "Error")
                    })
                except Exception as tg_err:
                    tg_results.append({"chat_id": cid, "success": False, "detail": str(tg_err)})
        elif not bot_token:
            tg_results.append({"chat_id": "none", "success": False, "detail": "BOT_TOKEN is not configured"})
        elif not chat_ids:
            tg_results.append({"chat_id": "none", "success": False, "detail": "No Chat IDs provided"})

        # 2. Dispatch Email
        email_result = {"success": False, "recipients": recipients, "detail": ""}
        if email_user and email_pass and recipients:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"🚨 [OPB SIGNAL TEST] {symbol} — {tier} {direction} (Score: {score}/100)"
            msg["From"] = f"OPB Trading Signals <{email_user}>"
            msg["To"] = ", ".join(recipients)

            plain_fallback = f"OPB SIGNAL ALERT: {symbol} | Price: {price} | SL: {stop_loss} | T1: {target_1} | Signal ID: {signal_id}"
            msg.attach(MIMEText(plain_fallback, "plain"))
            msg.attach(MIMEText(rich_html_email, "html"))

            try:
                with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
                    server.starttls()
                    server.login(email_user, email_pass)
                    server.send_message(msg)
                email_result["success"] = True
                email_result["detail"] = f"Delivered to {len(recipients)} recipient(s): {', '.join(recipients)}"
            except Exception as em_err:
                email_result["detail"] = str(em_err)
        else:
            email_result["detail"] = "Missing EMAIL_USER, EMAIL_PASS, or valid recipients in EMAIL_TO"

        return {
            "success": True,
            "signal_id": signal_id,
            "symbol": symbol,
            "telegram": {
                "attempted": bool(bot_token and chat_ids),
                "results": tg_results
            },
            "email": email_result,
            "timestamp": now_ist().strftime("%Y-%m-%d %H:%M:%S IST")
        }

    @app.post("/api/v1/admin/test-email")
    async def api_test_email(user: Any = Depends(dashboard._auth_deps.require_permission("modify_config"))):
        """Dispatch a live test email using current SMTP configuration."""
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        from core.datetime_ist import now_ist

        cfg = dashboard._cfg
        smtp_host = str(cfg.get("EMAIL_SMTP", "smtp.gmail.com")).strip()
        smtp_port = int(cfg.get("EMAIL_PORT", 587))
        email_user = str(cfg.get("EMAIL_USER", "")).strip()
        email_pass = str(cfg.get("EMAIL_PASS", "")).strip().replace(" ", "")
        email_to_raw = str(cfg.get("EMAIL_TO", "")).strip()

        recipients = [r.strip() for r in email_to_raw.split(",") if r.strip() and "@" in r]

        if not email_user or not email_pass:
            return {"success": False, "error": "EMAIL_USER or EMAIL_PASS is empty in configuration."}
        if not recipients:
            return {"success": False, "error": "No valid recipient email addresses in EMAIL_TO."}

        now = now_ist()
        time_str = now.strftime("%Y-%m-%d %H:%M:%S IST")

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <body style="font-family:sans-serif;background:#0f172a;color:#f8fafc;padding:20px;">
            <div style="background:#1e293b;border:1px solid #334155;border-radius:10px;padding:20px;max-width:550px;margin:0 auto;">
                <h2 style="color:#38bdf8;margin-top:0;">⚡ OPB Signal Notification Test</h2>
                <p>This is a live test notification verifying your SMTP credentials and multi-recipient routing.</p>
                <div style="background:#0f172a;padding:12px;border-radius:6px;margin:15px 0;">
                    <div><b>Timestamp:</b> {time_str}</div>
                    <div><b>Sender:</b> {email_user}</div>
                    <div><b>Recipients:</b> {', '.join(recipients)}</div>
                    <div><b>Status:</b> <span style="color:#10b981;font-weight:bold;">SMTP TLS Connected OK</span></div>
                </div>
                <div style="font-size:12px;color:#94a3b8;">OPB Trading System • 2026 Production Tier</div>
            </div>
        </body>
        </html>
        """

        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"⚡ [OPB LIVE TEST] Signal Notification Delivery Test ({now.strftime('%H:%M:%S')} IST)"
        msg["From"] = f"OPB Trading Signals <{email_user}>"
        msg["To"] = ", ".join(recipients)
        msg.attach(MIMEText(html_content, "html"))

        try:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
                server.starttls()
                server.login(email_user, email_pass)
                server.send_message(msg)
            return {
                "success": True,
                "message": f"Test email successfully sent to {len(recipients)} recipient(s): {', '.join(recipients)}",
                "recipients": recipients,
                "timestamp": time_str
            }
        except Exception as ex:
            return {
                "success": False,
                "error": f"SMTP Error: {str(ex)}"
            }
  # type: ignore[no-untyped-def]
    """Register admin control and config management routes.

    Args:
        app: FastAPI application instance.
        dashboard: EnterpriseDashboard instance.
        admin_only: FastAPI Depends for admin role.
        operator_or_admin: FastAPI Depends for operator or admin role.

    """
    # ── Config Management API ──────────────────────────────────────────────

    @app.get("/api/config")
    async def api_get_config(user: Any = Depends(dashboard._auth_deps.require_permission("modify_config"))):  # type: ignore[no-untyped-def]
        from core.notifications.url_resolver import get_deployment_base_url, get_public_base_url
        deployment_url = get_deployment_base_url(dashboard._cfg)
        admin_override = dashboard._cfg.get("PUBLIC_BASE_URL_ADMIN_OVERRIDE", "")
        return {
            "config": dashboard._cfg,
            "defaults_path": str(dashboard._resolve_defaults_path()),
            "config_path": str(dashboard._resolve_config_path()),
            "public_url": {
                "deployment_url": deployment_url,
                "admin_override": admin_override,
                "effective_url": get_public_base_url(dashboard._cfg),
                "admin_override_configurable": True,
                "deployment_url_editable": False,
                "required_permission": "modify_config",
            },
        }

    @app.get("/api/config/defaults")
    async def api_get_defaults(user: Any = Depends(dashboard._auth_deps.require_permission("modify_config"))):  # type: ignore[no-untyped-def]
        return dashboard._load_defaults()

    @app.post("/api/config/validate")
    async def api_validate_config(  # type: ignore[no-untyped-def]
        request: Request,
        user: Any = Depends(dashboard._auth_deps.require_permission("modify_config")),
    ):
        body = await request.json()
        return dashboard._validate_config_change(body)

    @app.post("/api/config/preview")
    async def api_preview_config(  # type: ignore[no-untyped-def]
        request: Request,
        user: Any = Depends(dashboard._auth_deps.require_permission("modify_config")),
    ):
        body = await request.json()
        return dashboard._preview_config_change(body)

    @app.post("/api/config/apply")
    async def api_apply_config(  # type: ignore[no-untyped-def]
        request: Request,
        user: Any = Depends(dashboard._auth_deps.require_permission("modify_config")),
    ):
        body = await request.json()
        return dashboard._apply_config_change(body, user.username)

    @app.get("/api/config/history")
    async def api_config_history(user: Any = Depends(dashboard._auth_deps.require_permission("modify_config"))):  # type: ignore[no-untyped-def]
        return dashboard._get_config_history()

    @app.get("/api/config/audit-log")
    async def api_config_audit_log(limit: int = 50, user: Any = Depends(dashboard._auth_deps.require_permission("view_logs"))):  # type: ignore[no-untyped-def]
        """Who changed which config keys, when — /api/config/history only
        lists backup filenames with no username/keys attached."""
        return dashboard._get_config_audit_log(limit=limit)

    @app.get("/api/config/drift")
    async def api_config_drift(user: Any = Depends(dashboard._auth_deps.require_permission("modify_config"))):  # type: ignore[no-untyped-def]
        """Detect configuration drift between live config and defaults."""
        try:
            defaults = dashboard._load_defaults()
            live = dict(dashboard._cfg)
            changed: list[dict[str, Any]] = []
            added: list[str] = []
            removed: list[str] = []

            for key in set(live) & set(defaults):
                live_val = live[key]
                default_val = defaults[key]
                live_s = json.dumps(live_val, sort_keys=True, default=str)
                default_s = json.dumps(default_val, sort_keys=True, default=str)
                if live_s != default_s:
                    changed.append({
                        "key": key,
                        "default": default_val,
                        "current": live_val,
                    })

            for key in set(live) - set(defaults):
                if not key.startswith("_"):
                    added.append(key)

            for key in set(defaults) - set(live):
                removed.append(key)

            total_keys = len(set(live) | set(defaults))
            drift_count = len(changed) + len(added) + len(removed)
            drift_pct = round((drift_count / max(total_keys, 1)) * 100, 1)

            return {
                "drift_pct": drift_pct,
                "drift_count": drift_count,
                "total_keys": total_keys,
                "changed_count": len(changed),
                "added_count": len(added),
                "removed_count": len(removed),
                "changes": changed,
                "added_keys": added,
                "removed_keys": removed[:50],
                "timestamp": time.time(),
            }
        except (ValueError, TypeError, KeyError, OSError) as exc:
            _log.warning("[DASH] Config drift check failed: %s", exc)
            return {"status": "error", "detail": str(exc)}

    @app.post("/api/config/rollback/{version}")
    async def api_rollback_config(  # type: ignore[no-untyped-def]
        version: str,
        user: Any = Depends(dashboard._auth_deps.require_permission("modify_config")),
    ):
        return dashboard._rollback_config(version, user.username)

    # ── Kill Switch API ────────────────────────────────────────────────────

    @app.post("/api/system/kill")
    async def api_kill(  # type: ignore[no-untyped-def]
        request: Request,
        user: Any = Depends(dashboard._auth_deps.require_permission("halt_trading")),
    ):
        body = await request.json()
        reason = str(body.get("reason", "Manual kill via dashboard"))
        result = dashboard._execute_kill(reason, user.username)
        try:
            dashboard._auth._audit_log(
                "kill_switch", user.username, "", {"action": "KILL", "reason": reason},
            )
        except (ValueError, AttributeError, TypeError, OSError) as e:
            _log.warning("[DASH] Kill switch audit log write failed: %s", e)
        return result

    @app.post("/api/system/resume")
    async def api_resume(  # type: ignore[no-untyped-def]
        request: Request,
        user: Any = Depends(dashboard._auth_deps.require_permission("halt_trading")),
    ):
        body = {}
        try:
            body = await request.json()
        except (ValueError, TypeError):
            pass
        reason = str(body.get("reason", "Manual resume via dashboard"))
        result = dashboard._execute_resume()
        try:
            dashboard._auth._audit_log(
                "kill_switch", user.username, "", {"action": "RESUME", "reason": reason},
            )
        except (ValueError, AttributeError, TypeError, OSError) as e:
            _log.warning("[DASH] Kill switch audit log write failed: %s", e)
        return result

    @app.post("/api/system/pause")
    async def api_pause(  # type: ignore[no-untyped-def]
        user: Any = Depends(dashboard._auth_deps.require_permission("halt_trading")),
    ):
        dashboard._pause_event.set()
        return {"status": "paused"}

    @app.post("/api/system/resume-entry")
    async def api_resume_entry(  # type: ignore[no-untyped-def]
        user: Any = Depends(dashboard._auth_deps.require_permission("halt_trading")),
    ):
        dashboard._pause_event.clear()
        return {"status": "resumed"}

    # ── Change Management API ──────────────────────────────────────────────

    @app.get("/api/changes/pending")
    async def api_changes_pending(user: Any = Depends(dashboard._auth_deps.require_permission("view_logs"))):  # type: ignore[no-untyped-def]
        """List all pending change proposals awaiting approval."""
        try:
            from core.change_management import get_change_manager
            mgr = get_change_manager(dashboard._cfg)
            pending = mgr.list_pending()
            return {
                "pending": [p.to_dict() for p in pending],
                "count": len(pending),
                "timestamp": time.time(),
            }
        except ImportError:
            return {"status": "unavailable", "detail": "ChangeManager not available"}
        except (ValueError, TypeError, AttributeError) as exc:
            _log.warning("[DASH] Changes pending failed: %s", exc)
            return {"status": "error", "detail": str(exc)}

    @app.post("/api/changes/propose")
    async def api_changes_propose(request: Request, user: Any = Depends(dashboard._auth_deps.require_permission("modify_config"))):  # type: ignore[no-untyped-def]
        """Propose a new configuration or parameter change."""
        try:
            body = await request.json()
            from core.change_management import get_change_manager
            mgr = get_change_manager(dashboard._cfg)
            prop = mgr.propose(
                change_type=body.get("change_type", "CONFIG"),
                target_key=body.get("target_key", ""),
                current_value=body.get("current_value"),
                proposed_value=body.get("proposed_value"),
                reason=body.get("reason", "No reason provided"),
                proposed_by=user.username,
                risk_level=body.get("risk_level", "NORMAL"),
            )
            return {
                "success": True,
                "change_id": prop.id_,
                "status": prop.status.value,
                "proposal": prop.to_dict(),
                "timestamp": time.time(),
            }
        except ImportError:
            return {"status": "unavailable", "detail": "ChangeManager not available"}
        except (ValueError, TypeError, AttributeError, RuntimeError) as exc:
            _log.warning("[DASH] Change propose failed: %s", exc)
            return {"status": "error", "detail": str(exc)}

    @app.post("/api/changes/approve/{change_id}")
    async def api_changes_approve(change_id: str, user: Any = Depends(dashboard._auth_deps.require_permission("modify_config"))):  # type: ignore[no-untyped-def]
        """Approve a pending change proposal."""
        try:
            from core.change_management import get_change_manager
            mgr = get_change_manager(dashboard._cfg)
            ok = mgr.approve(change_id, approved_by=user.username)
            return {
                "success": ok,
                "change_id": change_id,
                "status": "approved" if ok else "failed",
                "timestamp": time.time(),
            }
        except ImportError:
            return {"status": "unavailable", "detail": "ChangeManager not available"}
        except (ValueError, TypeError, AttributeError) as exc:
            _log.warning("[DASH] Change approve failed: %s", exc)
            return {"status": "error", "detail": str(exc)}

    @app.post("/api/changes/reject/{change_id}")
    async def api_changes_reject(change_id: str, request: Request, user: Any = Depends(dashboard._auth_deps.require_permission("modify_config"))):  # type: ignore[no-untyped-def]
        """Reject a pending change proposal."""
        try:
            body = await request.json()
            from core.change_management import get_change_manager
            mgr = get_change_manager(dashboard._cfg)
            reason = body.get("reason", "Rejected via dashboard")
            ok = mgr.reject(change_id, rejected_by=user.username, reason=reason)
            return {
                "success": ok,
                "change_id": change_id,
                "status": "rejected" if ok else "failed",
                "timestamp": time.time(),
            }
        except ImportError:
            return {"status": "unavailable", "detail": "ChangeManager not available"}
        except (ValueError, TypeError, AttributeError) as exc:
            _log.warning("[DASH] Change reject failed: %s", exc)
            return {"status": "error", "detail": str(exc)}

    @app.get("/api/changes/history")
    async def api_changes_history(user: Any = Depends(dashboard._auth_deps.require_permission("view_logs"))):  # type: ignore[no-untyped-def]
        """Get recent change proposals with audit trail."""
        try:
            from core.change_management import get_change_manager
            mgr = get_change_manager(dashboard._cfg)
            recent = mgr.list_recent(n=50)
            audit = mgr.get_audit_log(n=100)
            stats = mgr.get_stats()
            return {
                "recent": [p.to_dict() for p in recent],
                "audit_log": audit,
                "stats": stats,
                "timestamp": time.time(),
            }
        except ImportError:
            return {"status": "unavailable", "detail": "ChangeManager not available"}
        except (ValueError, TypeError, AttributeError) as exc:
            _log.warning("[DASH] Changes history failed: %s", exc)
            return {"status": "error", "detail": str(exc)}

    # ── Self-Test API ──────────────────────────────────────────────────────

    @app.post("/api/system/self-test")
    async def api_self_test(user: Any = Depends(dashboard._auth_deps.require_permission("view_state"))):  # type: ignore[no-untyped-def]
        """Run startup self-test to verify critical modules are healthy."""
        import json

        from core.db_utils import get_connection as _get_db_conn

        results = []
        all_pass = True

        # 1. Auth DB health
        try:
            stats = dashboard._auth.get_stats()
            results.append({"test": "auth_db", "status": "pass",
                "detail": f"{stats.get('total_users', 0)} users, {stats.get('active_sessions', 0)} active sessions"})
        except (ValueError, TypeError, OSError) as e:
            results.append({"test": "auth_db", "status": "fail", "detail": str(e)})
            all_pass = False

        # 2. State file readable
        try:
            state = dashboard._read_state()
            results.append({"test": "state_file", "status": "pass",
                "detail": f"{len(state)} keys, mode={state.get('execution_mode', 'unknown')}"})
        except (ValueError, OSError, json.JSONDecodeError) as e:
            results.append({"test": "state_file", "status": "fail", "detail": str(e)})
            all_pass = False

        # 3. Trades DB queryable
        try:
            conn = _get_db_conn(dashboard._db_path, timeout=2, row_factory=False)
            cursor = conn.execute("SELECT COUNT(*) FROM trades")
            trade_count = cursor.fetchone()[0]
            conn.close()
            results.append({"test": "trades_db", "status": "pass",
                "detail": f"{trade_count} trades"})
        except (OSError, ValueError) as e:
            results.append({"test": "trades_db", "status": "warn",
                "detail": f"{e} (non-fatal if no trades yet)"})

        # 4. Config available
        try:
            cfg_keys = len(dashboard._cfg)
            defaults_path = dashboard._resolve_defaults_path()
            defaults_ok = defaults_path.is_file()
            results.append({"test": "config", "status": "pass",
                "detail": f"{cfg_keys} keys loaded, defaults_file={defaults_ok}"})
            if not defaults_ok:
                results.append({"test": "defaults_file", "status": "warn",
                    "detail": f"Defaults file not found at {defaults_path}"})
        except (ValueError, OSError, json.JSONDecodeError) as e:
            results.append({"test": "config", "status": "fail", "detail": str(e)})
            all_pass = False

        # 5. Template rendering works
        try:
            dashboard._templates.get_template("login.html")
            results.append({"test": "templates", "status": "pass",
                "detail": "Login template loaded"})
        except (ValueError, TypeError, AttributeError) as e:
            results.append({"test": "templates", "status": "warn", "detail": str(e)})

        return {
            "overall": "PASS" if all_pass else "FAIL",
            "timestamp": time.time(),
            "results": results,
            "summary": f"{sum(1 for r in results if r['status'] == 'pass')} passed, "
                       f"{sum(1 for r in results if r['status'] == 'warn')} warnings, "
                       f"{sum(1 for r in results if r['status'] == 'fail')} failed",
        }

    # ── Admin Portfolio Analyzer API ───────────────────────────────────────

    @app.get("/admin/portfolio-analyzer")
    async def admin_portfolio_analyzer_page(request: Request, user: Any = Depends(dashboard._auth_deps.require_permission("view_state"))):  # type: ignore[no-untyped-def]
        nonce = getattr(request.state, "nonce", "")
        return dashboard._templates.TemplateResponse(
            request=request,
            name="admin_portfolio_analyzer.html",
            context=_page_context(user, nonce, "admin_portfolio_analyzer"),
        )

    @app.get("/api/v1/admin/broker/info/{broker_code}")
    async def api_broker_info(broker_code: str, user: Any = Depends(dashboard._auth_deps.require_permission("view_state"))):  # type: ignore[no-untyped-def]
        from core.admin_portfolio_analyzer import get_admin_portfolio_analyzer
        analyzer = get_admin_portfolio_analyzer()
        return analyzer.get_broker_info(broker_code)

    @app.post("/api/v1/admin/broker/fetch-holdings")
    async def api_broker_fetch_holdings(request: Request, user: Any = Depends(dashboard._auth_deps.require_permission("add_brokers"))):  # type: ignore[no-untyped-def]
        from core.admin_portfolio_analyzer import get_admin_portfolio_analyzer
        body = await request.json()
        broker_code = str(body.get("broker_code") or "zerodha")
        credentials = body.get("credentials") or {}
        analyzer = get_admin_portfolio_analyzer()
        holdings = analyzer.fetch_broker_holdings(broker_code, credentials=credentials)
        broker_info = analyzer.get_broker_info(broker_code)
        return {
            "status": "success",
            "broker_code": broker_code,
            "broker_name": broker_info.get("name", broker_code),
            "holdings": holdings,
            "count": len(holdings),
            "total_value": sum(h.get("quantity", 0) * h.get("current_price", 0) for h in holdings),
        }

    @app.post("/api/v1/admin/analyze-portfolio")
    async def api_analyze_portfolio(request: Request, user: Any = Depends(dashboard._auth_deps.require_permission("view_state"))):  # type: ignore[no-untyped-def]
        from core.admin_portfolio_analyzer import get_admin_portfolio_analyzer
        body = await request.json()
        user_name = str(body.get("user_name") or "Admin Inspected User")
        broker_code = str(body.get("broker_code") or "zerodha")
        raw_positions = body.get("positions") or []

        analyzer = get_admin_portfolio_analyzer()
        positions = analyzer.parse_portfolio(raw_positions)
        return analyzer.run_16_strategy_deep_scan(user_name, broker_code, positions)

    @app.get("/api/v1/admin/market-regime")
    async def api_get_market_regime(user: Any = Depends(dashboard._auth_deps.require_permission("view_state"))):  # type: ignore[no-untyped-def]
        from core.ai.market_regime_classifier import get_market_regime_classifier
        classifier = get_market_regime_classifier()
        # Sample NIFTY prices
        sample_prices = [23800.0 + i * 25.0 for i in range(20)]
        classification = classifier.classify_regime(sample_prices, vix_level=15.5)
        return classification

    @app.get("/api/v1/admin/broker-health")
    async def api_get_broker_health(user: Any = Depends(dashboard._auth_deps.require_permission("view_state"))):  # type: ignore[no-untyped-def]
        from core.adapters.broker_health_monitor import get_broker_health_monitor
        monitor = get_broker_health_monitor()
        statuses = monitor.ping_all_brokers()
        return {"timestamp": time.time(), "total_brokers": len(statuses), "brokers": statuses}

    @app.post("/api/v1/admin/auto-hedge")
    async def api_auto_hedge_portfolio(request: Request, user: Any = Depends(dashboard._auth_deps.require_permission("modify_risk_limits"))):  # type: ignore[no-untyped-def]
        from core.risk.auto_hedger import get_portfolio_auto_hedger
        body = await request.json()
        positions = body.get("positions") or []
        spot_nifty = float(body.get("spot_nifty") or 24250.0)
        hedger = get_portfolio_auto_hedger()
        return hedger.analyze_and_hedge(positions, spot_nifty=spot_nifty)

    @app.post("/api/v1/admin/execute-hedge")
    async def api_execute_hedge(request: Request, user: Any = Depends(dashboard._auth_deps.require_permission("modify_risk_limits"))):  # type: ignore[no-untyped-def]
        from core.risk.auto_hedger import get_portfolio_auto_hedger
        body = await request.json()
        hedge_id = body.get("hedge_id")
        instrument = body.get("instrument")
        action = body.get("action")
        is_dry_run = body.get("is_dry_run", True)

        hedger = get_portfolio_auto_hedger()
        result = hedger.execute_hedge(hedge_id, instrument, action, is_dry_run)
        try:
            dashboard._auth._audit_log(
                "hedge_execute", user.username, "",
                {"hedge_id": hedge_id, "instrument": instrument, "action": action, "is_dry_run": is_dry_run},
            )
        except (ValueError, AttributeError, TypeError, OSError) as e:
            _log.warning("[DASH] Hedge execution audit log write failed: %s", e)
        return result

    @app.post("/api/v1/admin/tax-loss-harvest")
    async def api_tax_loss_harvest(request: Request, user: Any = Depends(dashboard._auth_deps.require_permission("modify_risk_limits"))):  # type: ignore[no-untyped-def]
        from core.admin_portfolio_analyzer import get_admin_portfolio_analyzer
        from core.risk.tax_loss_harvester import get_tax_loss_harvester
        body = await request.json()
        raw_positions = body.get("positions") or []

        analyzer = get_admin_portfolio_analyzer()
        positions = analyzer.parse_portfolio(raw_positions)

        harvester = get_tax_loss_harvester()
        opps = harvester.scan_portfolio(positions)
        try:
            dashboard._auth._audit_log(
                "tax_loss_harvest_scan", user.username, "", {"positions_scanned": len(positions), "opportunities_found": len(opps)},
            )
        except (ValueError, AttributeError, TypeError, OSError) as e:
            _log.warning("[DASH] Tax-loss harvest audit log write failed: %s", e)
        return {"opportunities": [vars(o) for o in opps]}

    @app.post("/api/v1/admin/generate-report")
    async def api_generate_report(request: Request, user: Any = Depends(dashboard._auth_deps.require_permission("view_state"))):  # type: ignore[no-untyped-def]
        from core.ai.report_generator import get_report_builder
        body = await request.json()
        # body contains the full result of analyze-portfolio
        builder = get_report_builder()
        markdown = builder.generate_report(body)
        return {"markdown": markdown}

    @app.get("/api/v1/admin/system-status")
    async def api_system_status(user: Any = Depends(dashboard._auth_deps.require_permission("view_state"))):  # type: ignore[no-untyped-def]
        from core.ai.agentic_sentiment import get_agentic_sentiment
        from core.ai.live_indicators import get_live_indicator_engine
        # Redis is an optional dashboard acceleration/coordination dependency.
        # The status endpoint must remain observable when Redis is unavailable;
        # fail soft and report redis_connected=False instead of crashing the HUD.
        try:
            from core.execution.redis_pubsub import get_redis_bus
            bus = get_redis_bus()
        except (ImportError, ModuleNotFoundError) as exc:
            _log.warning("[DASH] Redis status unavailable: %s", exc)
            class _UnavailableRedis:
                is_connected = False
            bus = _UnavailableRedis()
        ind_engine = get_live_indicator_engine()
        agent = get_agentic_sentiment()

        vix = ind_engine.fetch_india_vix()

        if vix > 20.0:
            dyn_buf = 40
        elif vix < 15.0:
            dyn_buf = 10
        else:
            dyn_buf = 20

        mock_sentiment = agent.analyze_news("NIFTY", "Markets are steady.")

        return {
            "redis_connected": bus.is_connected,
            "india_vix": vix,
            "dynamic_cash_buffer_pct": dyn_buf,
            "agentic_active": agent.is_active,
            "latest_sentiment_score": mock_sentiment.score,
            "latest_sentiment_reason": mock_sentiment.reasoning
        }
