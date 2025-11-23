"""
routes/auth.py
Rotas: login, refresh, seed-admin, logout.
Modificadas para persistir refresh tokens (hashed) e permitir logout/revogação.
"""
from fastapi import APIRouter, HTTPException, Depends, Body
from ..schemas import LoginIn, Token, UserCreate
from .. import db, auth, config
from datetime import datetime, timedelta
import uuid
import pyotp

router = APIRouter()

@router.post("/login", response_model=Token)
async def login(data: LoginIn):
    user = await db.db.users.find_one({"username": data.username})
    if not user or not auth.verify_password(data.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Credenciais inválidas")
    access, refresh = auth.create_tokens(str(user["_id"]))
    # Armazenar refresh token hashed para maior segurança
    hashed = auth.pwd_context.hash(refresh)
    expires_at = datetime.utcnow() + timedelta(days=config.JWT_REFRESH_EXPIRE_DAYS)
    await db.db.refresh_tokens.update_one(
        {"user_id": str(user["_id"])},
        {"$set": {"user_id": str(user["_id"]), "token_hash": hashed, "expires_at": expires_at}},
        upsert=True
    )
    return {"access_token": access, "refresh_token": refresh}


@router.post("/login-step")
async def login_step(data: LoginIn):
    """Login em dois passos: se o usuário tiver MFA habilitado, retorna mfa_required + mfa_token (curta duração).
    Caso contrário, emite tokens normalmente (compatibilidade)."""
    user = await db.db.users.find_one({"username": data.username})
    if not user or not auth.verify_password(data.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Credenciais inválidas")

    if user.get("mfa_enabled", False):
        # Gera token de desafio para verificação MFA (curta validade)
        now = datetime.utcnow()
        payload = {"sub": str(user["_id"]), "purpose": "mfa", "exp": now + timedelta(minutes=5)}
        mfa_token = auth.jwt.encode(payload, config.JWT_SECRET, algorithm="HS256")
        return {"mfa_required": True, "mfa_token": mfa_token}

    # Sem MFA, emite tokens (comportamento antigo)
    access, refresh = auth.create_tokens(str(user["_id"]))
    hashed = auth.pwd_context.hash(refresh)
    expires_at = datetime.utcnow() + timedelta(days=config.JWT_REFRESH_EXPIRE_DAYS)
    await db.db.refresh_tokens.update_one(
        {"user_id": str(user["_id"])},
        {"$set": {"user_id": str(user["_id"]), "token_hash": hashed, "expires_at": expires_at}},
        upsert=True
    )
    return {"access_token": access, "refresh_token": refresh}


@router.post("/login-verify", response_model=Token)
async def login_verify(body: dict = Body(...)):
    """Recebe { mfa_token, code } — valida o mfa_token e o código TOTP, então emite tokens JWT."""
    mfa_token = body.get("mfa_token")
    code = body.get("code")
    if not mfa_token or not code:
        raise HTTPException(status_code=400, detail="mfa_token e code são obrigatórios")

    try:
        payload = auth.jwt.decode(mfa_token, config.JWT_SECRET, algorithms=["HS256"])
        if payload.get("purpose") != "mfa":
            raise Exception("Token inválido")
        user_id = payload.get("sub")
    except Exception:
        raise HTTPException(status_code=401, detail="mfa_token inválido ou expirado")

    user = await db.db.users.find_one({"_id": user_id})
    if not user or not user.get("mfa_secret"):
        raise HTTPException(status_code=400, detail="MFA não iniciado para este usuário")

    totp = pyotp.TOTP(user.get("mfa_secret"))
    if not totp.verify(str(code), valid_window=1):
        raise HTTPException(status_code=401, detail="Código MFA inválido")

    # Se OK, cria tokens e salva refresh hashed
    access, refresh = auth.create_tokens(str(user_id))
    hashed = auth.pwd_context.hash(refresh)
    expires_at = datetime.utcnow() + timedelta(days=config.JWT_REFRESH_EXPIRE_DAYS)
    await db.db.refresh_tokens.update_one(
        {"user_id": str(user_id)},
        {"$set": {"user_id": str(user_id), "token_hash": hashed, "expires_at": expires_at}},
        upsert=True
    )
    return {"access_token": access, "refresh_token": refresh}

@router.post("/refresh", response_model=Token)
async def refresh(token: str = Body(...)):
    try:
        payload = auth.jwt.decode(token, config.JWT_SECRET, algorithms=["HS256"])
        user_id = payload.get("sub")
    except Exception:
        raise HTTPException(status_code=401, detail="Refresh inválido")
    # Verifica token hashed salvo
    doc = await db.db.refresh_tokens.find_one({"user_id": str(user_id)})
    if not doc or not auth.pwd_context.verify(token, doc.get("token_hash", "")):
        raise HTTPException(status_code=401, detail="Refresh inválido ou revogado")
    # Rotaciona tokens: cria novos e atualiza hash
    access, new_refresh = auth.create_tokens(user_id)
    new_hashed = auth.pwd_context.hash(new_refresh)
    expires_at = datetime.utcnow() + timedelta(days=config.JWT_REFRESH_EXPIRE_DAYS)
    await db.db.refresh_tokens.update_one({"user_id": str(user_id)}, {"$set": {"token_hash": new_hashed, "expires_at": expires_at}})
    return {"access_token": access, "refresh_token": new_refresh}

@router.post("/logout")
async def logout(token: str = Body(...)):
    """
    Logout: revoga refresh token enviado pelo cliente.
    """
    try:
        payload = auth.jwt.decode(token, config.JWT_SECRET, algorithms=["HS256"])
        user_id = payload.get("sub")
    except Exception:
        # Se o token inválido, tenta apenas remover qualquer refresh para segurança
        raise HTTPException(status_code=401, detail="Refresh inválido")
    # Remove refresh token entry (revoga)
    await db.db.refresh_tokens.delete_one({"user_id": str(user_id)})
    return {"status": "ok"}

@router.post("/seed-admin", summary="Criar admin inicial (apenas se nenhum existir)")
async def seed_admin(body: UserCreate = Body(...), secret: str = Body(...)):
    # Segurança: exige INIT_ADMIN_SECRET e somente se não existir admin
    if config.INIT_ADMIN_SECRET is None or secret != config.INIT_ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Secret inválido")
    existing = await db.db.users.count_documents({"role": "admin"})
    if existing > 0:
        raise HTTPException(status_code=400, detail="Admin já existe")
    user_doc = {
        "_id": str(uuid.uuid4()),
        "username": body.username,
        "email": body.email,
        "password_hash": auth.hash_password(body.password),
        "role": "admin",
        "created_at": datetime.utcnow(),
        "phone": body.phone
    }
    await db.db.users.insert_one(user_doc)
    return {"status": "ok"}


@router.get("/me")
async def me(user=Depends(auth.get_current_user)):
    """Retorna informações básicas do usuário autenticado."""
    if not user:
        raise HTTPException(status_code=401, detail="Usuário não autenticado")
    return {
        "_id": user.get("_id"),
        "id": user.get("_id"),
        "username": user.get("username"),
        "name": user.get("name") or user.get("username"),
        "email": user.get("email"),
        "role": user.get("role"),
        "mfa_enabled": user.get("mfa_enabled", False)
    }
