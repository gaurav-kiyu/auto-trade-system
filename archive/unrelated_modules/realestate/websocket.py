"""Real-time WebSocket Notifications — live push for the real estate platform.

Provides:
  - WebSocketNotificationManager: manages active connections per user
  - WebSocket endpoint: /ws/notifications/{user_id}
  - Auto-reconnect support via ping/pong
  - Broadcast methods for common notification types
  - Integrates with the existing NotificationEngine

Usage in startup:
    from realestate.websocket import ws_notification_manager, create_websocket_router
    app.include_router(create_websocket_router())

Client (JS):
    const ws = new WebSocket("ws://host:port/ws/notifications/user123");
    ws.onmessage = (event) => {
        const notif = JSON.parse(event.data);
        showToast(notif.title, notif.message);
    };
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

_log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# WebSocket Connection Manager
# ═══════════════════════════════════════════════════════════════════════════════

class WebSocketNotificationManager:
    """Manages active WebSocket connections per user.

    Features:
      - User-to-connections mapping (one user can have multiple tabs)
      - Broadcast to a single user or all users
      - Heartbeat ping/pong every 30s to keep connections alive
      - Automatic cleanup on disconnect
      - Connection stats
    """

    def __init__(self) -> None:
        # user_id -> list of (websocket, connected_at)
        self._connections: dict[str, list[tuple[WebSocket, float]]] = {}
        self._total_connections = 0
        self._total_messages_sent = 0
        self._heartbeat_task: asyncio.Task | None = None

    # ── Connection Management ─────────────────────────────────────────────

    async def connect(self, websocket: WebSocket, user_id: str) -> None:
        """Accept a new WebSocket connection for a user."""
        await websocket.accept()
        self._connections.setdefault(user_id, []).append((websocket, time.time()))
        self._total_connections += 1
        _log.info("[WS] User %s connected (%d active connections)", user_id, self._count_connections(user_id))

        # Send welcome message
        await self._send_json(websocket, {
            "type": "connected",
            "user_id": user_id,
            "timestamp": time.time(),
            "message": "Real-time notifications active",
        })

    async def disconnect(self, websocket: WebSocket, user_id: str) -> None:
        """Remove a WebSocket connection."""
        user_conns = self._connections.get(user_id, [])
        self._connections[user_id] = [(ws, ts) for ws, ts in user_conns if ws != websocket]
        if not self._connections[user_id]:
            self._connections.pop(user_id, None)
        _log.info("[WS] User %s disconnected (%d remaining)", user_id, self._count_connections(user_id))

    # ── Sending ───────────────────────────────────────────────────────────

    async def send_to_user(self, user_id: str, message: dict[str, Any]) -> int:
        """Send a message to all connections of a user. Returns count of recipients."""
        user_conns = self._connections.get(user_id, [])
        sent = 0
        for websocket, _ in user_conns:
            try:
                await self._send_json(websocket, message)
                sent += 1
                self._total_messages_sent += 1
            except Exception:
                # Connection might be closed — will be cleaned up on next disconnect
                pass
        return sent

    async def broadcast(self, message: dict[str, Any]) -> int:
        """Broadcast a message to all connected users. Returns count of recipients."""
        total = 0
        for user_id in list(self._connections.keys()):
            total += await self.send_to_user(user_id, message)
        return total

    async def notify_enquiry(self, owner_id: str, property_title: str, enquirer_name: str, property_id: str) -> int:
        """Send real-time notification for a new enquiry."""
        return await self.send_to_user(owner_id, {
            "type": "enquiry",
            "title": "New Enquiry Received",
            "message": f"{enquirer_name} is interested in \"{property_title}\"",
            "action_url": f"/realestate/property/{property_id}",
            "related_id": property_id,
            "timestamp": time.time(),
        })

    async def notify_lead_update(self, broker_id: str, lead_name: str, new_status: str, lead_id: str) -> int:
        """Send real-time notification for lead status change."""
        return await self.send_to_user(broker_id, {
            "type": "lead_update",
            "title": "Lead Status Updated",
            "message": f"Lead {lead_name} moved to \"{new_status}\"",
            "action_url": "/realestate/leads",
            "related_id": lead_id,
            "timestamp": time.time(),
        })

    async def notify_auction(self, user_id: str, property_title: str, event: str, auction_id: str, amount: float = 0) -> int:
        """Send real-time auction notification (outbid/won/starting)."""
        titles = {
            "outbid": "You've Been Outbid! ⚡",
            "won": "🎉 Auction Won!",
            "starting": "Auction Starting Soon ⏰",
        }
        messages = {
            "outbid": f"Someone placed a higher bid on \"{property_title}\" — ₹{amount:,.0f}",
            "won": f"Congratulations! You won \"{property_title}\" at ₹{amount:,.0f}",
            "starting": f"Auction for \"{property_title}\" is about to start",
        }
        return await self.send_to_user(user_id, {
            "type": "auction",
            "event": event,
            "title": titles.get(event, "Auction Update"),
            "message": messages.get(event, f"Auction update for \"{property_title}\""),
            "action_url": f"/realestate/auctions/{auction_id}",
            "related_id": auction_id,
            "timestamp": time.time(),
        })

    async def notify_system(self, user_id: str, title: str, message: str, action_url: str = "") -> int:
        """Send a system notification."""
        return await self.send_to_user(user_id, {
            "type": "system",
            "title": title,
            "message": message,
            "action_url": action_url,
            "timestamp": time.time(),
        })

    # ── Heartbeat ─────────────────────────────────────────────────────────

    async def start_heartbeat(self, interval: float = 30.0) -> None:
        """Start the periodic heartbeat to keep connections alive."""
        if self._heartbeat_task is not None and not self._heartbeat_task.done():
            return  # Already running

        async def _heartbeat_loop() -> None:
            while True:
                await asyncio.sleep(interval)
                await self._ping_all()

        self._heartbeat_task = asyncio.create_task(_heartbeat_loop())
        _log.debug("[WS] Heartbeat started (interval=%ds)", interval)

    async def stop_heartbeat(self) -> None:
        """Stop the heartbeat task."""
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            self._heartbeat_task = None
            _log.debug("[WS] Heartbeat stopped")

    async def _ping_all(self) -> None:
        """Send a ping to all connections to keep them alive."""
        now = time.time()
        for user_id, conns in list(self._connections.items()):
            for websocket, _ in conns:
                try:
                    await self._send_json(websocket, {"type": "ping", "timestamp": now})
                except Exception:
                    pass

    # ── Stats ─────────────────────────────────────────────────────────────

    def get_connected_users(self) -> int:
        return len(self._connections)

    def get_total_connections(self) -> int:
        return self._total_connections

    def get_messages_sent(self) -> int:
        return self._total_messages_sent

    def get_user_ids(self) -> list[str]:
        return list(self._connections.keys())

    def _count_connections(self, user_id: str) -> int:
        return len(self._connections.get(user_id, []))

    def get_stats(self) -> dict[str, Any]:
        return {
            "connected_users": self.get_connected_users(),
            "total_connections_lifetime": self._total_connections,
            "messages_sent": self._total_messages_sent,
            "user_ids": self.get_user_ids(),
        }

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    async def _send_json(websocket: WebSocket, data: dict[str, Any]) -> None:
        """Send a JSON message via WebSocket."""
        await websocket.send_text(json.dumps(data, default=str))


# Global manager singleton
_ws_manager: WebSocketNotificationManager | None = None


def get_ws_manager() -> WebSocketNotificationManager:
    """Get or create the global WebSocket manager singleton."""
    global _ws_manager
    if _ws_manager is None:
        _ws_manager = WebSocketNotificationManager()
    return _ws_manager


# ═══════════════════════════════════════════════════════════════════════════════
# WebSocket Router
# ═══════════════════════════════════════════════════════════════════════════════

def create_websocket_router() -> APIRouter:
    """Create the WebSocket notification router."""
    router = APIRouter(tags=["Real Estate WebSocket"])
    manager = get_ws_manager()

    @router.websocket("/ws/notifications/{user_id}")
    async def websocket_notifications(websocket: WebSocket, user_id: str):
        """WebSocket endpoint for real-time notifications.

        Connect: ws://host/ws/notifications/{user_id}
        Messages received from client (heartbeat response):
            {"type": "pong"}
        Messages sent to client:
            {"type": "connected", "user_id": "..."}
            {"type": "ping", "timestamp": ...}
            {"type": "enquiry|lead_update|auction|system", "title": "...", "message": "..."}
        """
        await manager.connect(websocket, user_id)

        try:
            # Start heartbeat
            asyncio.create_task(manager.start_heartbeat())

            # Listen for incoming messages (heartbeat pongs)
            while True:
                try:
                    data = await asyncio.wait_for(websocket.receive_text(), timeout=60)
                    try:
                        msg = json.loads(data)
                        if msg.get("type") == "pong":
                            # Respond to keep connection alive
                            await manager._send_json(websocket, {"type": "pong_ack", "timestamp": time.time()})
                    except (json.JSONDecodeError, TypeError):
                        _log.debug("[WS] Invalid message from user %s", user_id)
                except asyncio.TimeoutError:
                    # Send ping to check connection
                    try:
                        await manager._send_json(websocket, {"type": "ping", "timestamp": time.time()})
                    except Exception:
                        break

        except WebSocketDisconnect:
            _log.debug("[WS] User %s disconnected (WebSocketDisconnect)", user_id)
        except Exception as exc:
            _log.debug("[WS] User %s connection error: %s", user_id, exc)
        finally:
            await manager.disconnect(websocket, user_id)

    return router
