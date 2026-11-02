"""
WebSocket Live Push Service for Real-Time IoT Vending.
Enables the cloud backend to instantly push dispense commands to the ESP32
the exact millisecond Razorpay triggers the payment webhook (Zero-Polling Architecture).
"""
import asyncio
import json
import logging
from typing import Dict, Any, Optional
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class DeviceWebSocketManager:
    """
    Manages active persistent WebSocket connections for 1,000+ vending machines.
    Routes targeted push events directly to specific machines by device_id.
    """
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.main_loop: Optional[asyncio.AbstractEventLoop] = None

    def set_event_loop(self, loop: asyncio.AbstractEventLoop):
        self.main_loop = loop

    async def connect(self, device_id: str, websocket: WebSocket):
        await websocket.accept()
        # Clean canonical device ID
        clean_id = device_id.strip()
        self.active_connections[clean_id] = websocket
        if not self.main_loop:
            try:
                self.main_loop = asyncio.get_running_loop()
            except RuntimeError:
                pass
        logger.info(f"[WebSocket ⚡] Machine '{clean_id}' connected! Ready for instant push dispensing.")

    def disconnect(self, device_id: str):
        clean_id = device_id.strip()
        if clean_id in self.active_connections:
            del self.active_connections[clean_id]
            logger.info(f"[WebSocket 🔌] Machine '{clean_id}' disconnected.")

    def is_connected(self, device_id: str) -> bool:
        return device_id.strip() in self.active_connections

    async def send_vend_command(self, device_id: str, payload: Dict[str, Any]) -> bool:
        """
        Asynchronously sends instant vend payload directly to the ESP32.
        """
        clean_id = device_id.strip()
        ws = self.active_connections.get(clean_id)
        if not ws:
            logger.info(f"[WebSocket] Machine '{clean_id}' is not connected via WebSocket (falling back to pending queue).")
            return False

        try:
            logger.info(f"[WebSocket ⚡ PUSH] Pushing INSTANT vend command to machine '{clean_id}': {payload}")
            await ws.send_json(payload)
            return True
        except Exception as e:
            logger.warning(f"[WebSocket ✗] Error pushing to '{clean_id}': {e}")
            self.disconnect(clean_id)
            return False

    def push_vend_command_sync(self, device_id: str, payload: Dict[str, Any]) -> bool:
        """
        Safe bridge allowing synchronous or background webhook workers to dispatch
        an instant WebSocket push to the ESP32 without blocking.
        """
        clean_id = device_id.strip()
        if clean_id not in self.active_connections:
            return False

        try:
            # Check if we are already in an active running event loop
            loop = None
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                pass

            target_loop = loop or self.main_loop
            if target_loop and target_loop.is_running():
                asyncio.run_coroutine_threadsafe(self.send_vend_command(clean_id, payload), target_loop)
                return True
            else:
                # Run temporary loop if no loop active
                asyncio.run(self.send_vend_command(clean_id, payload))
                return True
        except Exception as err:
            logger.warning(f"[WebSocket Bridge] Notice during sync push to '{clean_id}': {err}")
            return False


# Global singleton instance
ws_manager = DeviceWebSocketManager()
