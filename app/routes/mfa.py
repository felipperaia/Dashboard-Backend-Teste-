from fastapi import APIRouter, Depends, HTTPException, Body
from .. import db, auth
import pyotp
from datetime import datetime

router = APIRouter()


@router.post("/setup")
async def mfa_setup(user=Depends(auth.get_current_user)):
    """Gera secret TOTP e retorna otpauth URL. O front-end pode gerar QR a partir do otpauth_url.
    Guarda o secret em users._id -> mfa_secret.
    """
    uid = user.get("_id")
    if not uid:
        raise HTTPException(status_code=401, detail="Usuário não autenticado")
    secret = pyotp.random_base32()
    otpauth = pyotp.totp.TOTP(secret).provisioning_uri(name=user.get("email") or uid, issuer_name="SiloMonitor")
    await db.db.users.update_one({"_id": uid}, {"$set": {"mfa_secret": secret, "mfa_enabled": False, "mfa_setup_at": datetime.utcnow()}})
    return {"secret": secret, "otpauth_url": otpauth}


@router.post("/verify")
async def mfa_verify(
    token: str = Body(..., embed=True),
    user=Depends(auth.get_current_user),
):
    uid = user.get("_id")
    if not uid:
        raise HTTPException(status_code=401, detail="Usuário não autenticado")
    u = await db.db.users.find_one({"_id": uid})
    if not u or not u.get("mfa_secret"):
        raise HTTPException(status_code=400, detail="MFA não inicializado")
    totp = pyotp.TOTP(u["mfa_secret"])
    ok = totp.verify(token, valid_window=1)
    if not ok:
        raise HTTPException(status_code=401, detail="Token inválido")
    await db.db.users.update_one(
        {"_id": uid},
        {"$set": {"mfa_enabled": True}}
    )
    return {"ok": True}
