"""
routes/notifications.py
Endpoints:
- GET /api/notifications/vapid_public  -> retorna VAPID_PUBLIC_KEY (para frontend)
- POST /api/notifications/subscribe   -> salva subscription (body = subscription JSON)
- POST /api/notifications/unsubscribe -> remove subscription (body.endpoint)
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from .. import config, db, auth
from datetime import datetime
import uuid
from typing import Optional
from fastapi import Body
from ..services import notification as notification_service

router = APIRouter()

@router.get("/vapid_public")
async def get_vapid_public():
    if not config.VAPID_PUBLIC_KEY:
        raise HTTPException(status_code=404, detail="VAPID key not configured")
    return {"vapid_public_key": config.VAPID_PUBLIC_KEY}

@router.post("/subscribe")
async def subscribe(request: Request, user=Depends(auth.get_current_user)):
    payload = await request.json()
    endpoint = payload.get("endpoint")
    if not endpoint:
        raise HTTPException(status_code=400, detail="endpoint required")
    sub_doc = {
        "_id": str(uuid.uuid4()),
        "endpoint": endpoint,
        "keys": payload.get("keys"),
        "user_id": user.get("_id") if user else None,
        "silo_id": payload.get("silo_id"),  # optional: frontend can indicate interest in a silo
        "created_at": datetime.utcnow()
    }
    await db.db.push_subscriptions.update_one({"endpoint": endpoint}, {"$set": sub_doc}, upsert=True)
    return {"status": "ok"}

@router.post("/unsubscribe")
async def unsubscribe(body: dict):
    endpoint = body.get("endpoint")
    if not endpoint:
        raise HTTPException(status_code=400, detail="endpoint required")
    await db.db.push_subscriptions.delete_one({"endpoint": endpoint})
    return {"status": "ok"}

# Novo endpoint: listar subscriptions (admin only)
@router.get("/admin/subscriptions")
async def list_subscriptions(admin=Depends(auth.admin_required)):
    """
    Retorna lista de push_subscriptions.
    A informação sensível (keys) é omitida por padrão para segurança.
    Acesso restrito a admins (dependência admin_required).
    """
    cursor = db.db.push_subscriptions.find({}).sort("created_at", -1).limit(1000)
    out = []
    async for s in cursor:
        out.append({
            "id": s.get("_id"),
            "endpoint": s.get("endpoint"),
            "user_id": s.get("user_id"),
            "silo_id": s.get("silo_id"),
            "created_at": s.get("created_at")
            # keys omitted intentionally
        })
    return out


@router.post("/test")
async def test_notify(email: Optional[str] = Body(None), phone: Optional[str] = Body(None), telegram_chat_id: Optional[str] = Body(None), user=Depends(auth.get_current_user)):
    """Endpoint para envio de notificações de teste (admin/operator)."""
    if user.get("role") not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Admin or operator required")
    text = f"Teste de notificação {datetime.utcnow().isoformat()}"
    sent = []
    if email:
        await notification_service.send_email(email, "Teste SiloMonitor", text)
        sent.append("email")
    if phone:
        await notification_service.send_sms_twilio(phone, text)
        sent.append("sms")
    if telegram_chat_id:
        await notification_service.send_telegram(telegram_chat_id, text)
        sent.append("telegram")
    return {"sent": sent}
