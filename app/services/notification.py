"""
services/notification.py
Enviar notificações por Telegram e Web Push (pywebpush).
NOTA: suporte a SMS via email-to-sms foi DESABILITADO (comentado) — não será usado
a menos que você reative explicitamente e configure credenciais SMTP.
"""
import httpx
from .. import config, db
import asyncio
from typing import Dict, Any
from pywebpush import webpush, WebPushException
import json
import logging
import smtplib
from email.message import EmailMessage
import httpx
from ..services import ws as ws_service

logger = logging.getLogger("notification")

async def send_telegram(chat_id: str, text: str):
    if not config.TELEGRAM_BOT_TOKEN:
        logger.debug("Telegram token não configurado; pulando envio Telegram")
        return
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    async with httpx.AsyncClient() as client:
        await client.post(url, json={"chat_id": chat_id, "text": text})


def _send_email_sync(host: str, port: int, user: str, password: str, sender: str, to: str, subject: str, body: str, timeout: int = 15):
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP(host, port, timeout=timeout) as server:
        server.starttls()
        server.login(user, password)
        server.send_message(msg)


async def send_email(to: str, subject: str, body: str):
    """Enviar email (rodando send sync em executor). Usa configurações de config.SMTP_*.
    Para SendGrid configure SMTP_USER=apikey e SMTP_PASS=<SENDGRID_API_KEY>.
    """
    if not config.SMTP_HOST or not config.SMTP_PORT or not config.SMTP_USER or not config.SMTP_PASS:
        logging.getLogger("notification").warning("SMTP não configurado; pulando envio de email para %s", to)
        return
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _send_email_sync, config.SMTP_HOST, config.SMTP_PORT, config.SMTP_USER, config.SMTP_PASS, getattr(config, "SMTP_FROM", config.SMTP_USER or "no-reply@example.com"), to, subject, body)


async def send_sms_twilio(to_number: str, body: str):
    """Envia SMS via Twilio REST API usando httpx (async). Configure TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM em config.py (env)."""
    if not getattr(config, "TWILIO_ACCOUNT_SID", None) or not getattr(config, "TWILIO_AUTH_TOKEN", None) or not getattr(config, "TWILIO_FROM", None):
        logging.getLogger("notification").warning("Twilio não configurado; pulando SMS para %s", to_number)
        return
    url = f"https://api.twilio.com/2010-04-01/Accounts/{config.TWILIO_ACCOUNT_SID}/Messages.json"
    auth = (config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN)
    data = {"From": config.TWILIO_FROM, "To": to_number, "Body": body}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(url, data=data, auth=auth)
        if r.status_code >= 300:
            logging.getLogger("notification").error("Twilio SMS falhou (%s): %s", r.status_code, r.text)
            # não raise para não quebrar pipeline
        return

def _vapid_auth():
    # Retorna dict com chave privada/publica se disponíveis
    if not config.VAPID_PRIVATE_KEY or not config.VAPID_PUBLIC_KEY:
        return None
    return {
        "vapid_private_key": config.VAPID_PRIVATE_KEY,
        "vapid_claims": {"sub": f"mailto:{config.SMTP_USER or 'no-reply@example.com'}"}
    }

async def send_webpush(subscription_info: Dict[str, Any], payload: str):
    """
    Envia Web Push usando pywebpush. subscription_info deve ser o objeto retornado
    por PushManager.subscribe() (endpoint + keys.p256dh + keys.auth).
    """
    vapid = _vapid_auth()
    if not vapid:
        logger.warning("VAPID keys não configuradas; pulando envio WebPush")
        return
    try:
        webpush(
            subscription_info=subscription_info,
            data=payload,
            vapid_private_key=vapid["vapid_private_key"],
            vapid_claims=vapid["vapid_claims"]
        )
    except WebPushException as ex:
        logger.exception("Falha ao enviar webpush: %s", ex)
        # Se for 410/404 do endpoint remova a subscription (tratada no caller)
        raise

# -----------------------------------------------------------
# SMS fallback: função comentada / desabilitada por padrão.
# Para reativar:
#  - configurar SMTP_* no .env
#  - implementar segurança e validação adicional
# -----------------------------------------------------------
async def send_sms_via_email(phone: str, carrier_gateway: str, subject: str, body: str):
    """
    FUNÇÃO DESABILITADA:
    Implementação do envio de SMS via gateway de email foi intencionalmente
    desativada e comentada. Se você precisar habilitar, implemente com cautela:
    - valide phone e carrier_gateway,
    - configure SMTP_* no .env,
    - habilite TLS/STARTTLS,
    - monitore limites de envio.
    """
    logger.info("send_sms_via_email está desabilitado. Para habilitar, edite services/notification.py e configure SMTP_* no .env.")
    return

# -----------------------------------------------------------
# Notify pipeline (usa Telegram e WebPush; não usa SMS por padrão)
# -----------------------------------------------------------
async def notify_alert(alert: Dict[str, Any]):
    """
    Busca responsáveis do silo e envia notificações:
    - Telegram para silo.responsible.telegram_chat_id
    - WebPush para subscriptions relacionadas ao silo (campo silo_id) ou globais
    """
    silo = await db.db.silos.find_one({"_id": alert["silo_id"]})
    silo_name = silo.get("name") if silo else "Silo"
    text = f"[{alert['level'].upper()}] {silo_name}: {alert['message']} (valor={alert.get('value')})"

    # Telegram
    chat_id = silo.get("responsible", {}).get("telegram_chat_id") if silo else None
    if chat_id:
        await send_telegram(chat_id, text)

    # Email
    email_to = silo.get("responsible", {}).get("email") if silo else None
    if email_to:
        try:
            await send_email(email_to, f"Alerta {silo_name}", text)
        except Exception:
            logger.exception("Erro enviando email para %s", email_to)

    # SMS
    phone = silo.get("responsible", {}).get("phone") if silo else None
    if phone:
        try:
            await send_sms_twilio(phone, text)
        except Exception:
            logger.exception("Erro enviando SMS para %s", phone)

    # WebPush: buscar subscriptions específicas para este silo + globais (silo_id=null)
    subs_cursor = db.db.push_subscriptions.find({"$or": [{"silo_id": alert["silo_id"]}, {"silo_id": None}]})
    async for sub in subs_cursor:
        try:
            subscription_info = {
                "endpoint": sub["endpoint"],
                "keys": sub.get("keys", {})
            }
            # pywebpush é síncrono, executamos no executor para não bloquear loop async
            await asyncio.get_event_loop().run_in_executor(None, lambda: send_webpush_sync(subscription_info, json.dumps({"title": "Silo Monitor", "body": text})))
        except Exception as e:
            logger.exception("Erro enviando webpush; removendo subscription possivelmente inválida: %s", e)
            try:
                await db.db.push_subscriptions.delete_one({"_id": sub["_id"]})
            except Exception:
                pass
    # Se existir manager de websocket, também broadcast
    try:
        await ws_service.manager.broadcast(json.dumps({"type": "alert", "silo_id": alert.get("silo_id"), "level": alert.get("level"), "message": alert.get("message"), "timestamp": alert.get("timestamp")}))
    except Exception:
        logger.debug("WebSocket manager não disponível ou falha no broadcast")

    return

# helper síncrono para chamar webpush dentro do executor (pywebpush é síncrono)
def send_webpush_sync(subscription_info, payload):
    vapid = _vapid_auth()
    if not vapid:
        return
    webpush(subscription_info=subscription_info, data=payload, vapid_private_key=vapid["vapid_private_key"], vapid_claims=vapid["vapid_claims"])
