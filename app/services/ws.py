from typing import List
import asyncio
import json

class ConnectionManager:
    def __init__(self):
        self.active_connections: List = []
        self._lock = asyncio.Lock()

    async def connect(self, websocket):
        async with self._lock:
            self.active_connections.append(websocket)

    async def disconnect(self, websocket):
        async with self._lock:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)

    async def send_personal_message(self, message: str, websocket):
        await websocket.send_text(message)

    async def broadcast(self, message: str):
        # envia para todas as conexões ativas; se falhar remove
        async with self._lock:
            to_remove = []
            for ws in list(self.active_connections):
                try:
                    await ws.send_text(message)
                except Exception:
                    to_remove.append(ws)
            for ws in to_remove:
                if ws in self.active_connections:
                    self.active_connections.remove(ws)


# manager global
manager = ConnectionManager()
