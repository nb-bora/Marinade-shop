from typing import Dict, List
from fastapi import WebSocket
import json


class KdsConnectionManager:
    def __init__(self):
        # Maps (restaurant_id, station) -> List[WebSocket]
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, restaurant_id: str, station: str):
        await websocket.accept()
        key = f"{restaurant_id}:{station}"
        if key not in self.active_connections:
            self.active_connections[key] = []
        self.active_connections[key].append(websocket)

    def disconnect(self, websocket: WebSocket, restaurant_id: str, station: str):
        key = f"{restaurant_id}:{station}"
        if key in self.active_connections:
            if websocket in self.active_connections[key]:
                self.active_connections[key].remove(websocket)
            if not self.active_connections[key]:
                del self.active_connections[key]

    async def broadcast_ticket_event(
        self, restaurant_id: str, station: str, event_data: dict
    ):
        key = f"{restaurant_id}:{station}"
        if key in self.active_connections:
            message = json.dumps(event_data, default=str)
            for connection in self.active_connections[key]:
                try:
                    await connection.send_text(message)
                except Exception:
                    pass


kds_manager = KdsConnectionManager()
