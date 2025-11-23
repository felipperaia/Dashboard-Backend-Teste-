"""
routes/alerts.py
Listar alertas e marcar como acknowledged.
"""
from fastapi import APIRouter, Depends, HTTPException
from .. import db, auth
from typing import List
from ..schemas import AlertOut
from datetime import datetime
from fastapi import WebSocket, WebSocketDisconnect
from ..services import ws as ws_service

router = APIRouter()

@router.get("/", response_model=List[dict])
async def list_alerts(_=Depends(auth.get_current_user)):
    cursor = db.db.alerts.find({}).sort("timestamp", -1).limit(100)
    res = []
    async for a in cursor:
        res.append(a)
    return res

@router.post("/ack/{alert_id}")
async def ack_alert(alert_id: str, user=Depends(auth.get_current_user)):
    await db.db.alerts.update_one({"_id": alert_id}, {"$set": {"acknowledged": True, "ack_by": user["_id"], "ack_at": datetime.utcnow()}})
    # Registrar auditoria (omissão por brevidade)
    return {"status": "ok"}


@router.websocket("/ws")
async def websocket_alerts_endpoint(websocket: WebSocket):
    """WebSocket endpoint para enviar alertas em tempo real ao frontend.
    Frontend deve se conectar em: ws://HOST/api/alerts/ws
    """
    await websocket.accept()
    await ws_service.manager.connect(websocket)
    try:
        while True:
            # apenas mantemos a conexão aberta; cliente pode enviar ping messages opcionais
            data = await websocket.receive_text()
            # ecoa mensagem de volta (opcional)
            await websocket.send_text(f"pong: {data}")
    except WebSocketDisconnect:
        await ws_service.manager.disconnect(websocket)
