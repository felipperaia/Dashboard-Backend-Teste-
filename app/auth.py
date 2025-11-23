"""
auth.py
Autenticação JWT, hashing de senhas e dependências do FastAPI.
"""
from datetime import datetime, timedelta
from jose import jwt, JWTError
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from passlib.context import CryptContext
from . import config, db

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain, hashed) -> bool:
    return pwd_context.verify(plain, hashed)

def create_tokens(user_id: str):
    now = datetime.utcnow()
    access_payload = {
        "sub": str(user_id),
        "exp": now + timedelta(minutes=config.JWT_ACCESS_EXPIRE_MIN)
    }
    refresh_payload = {
        "sub": str(user_id),
        "exp": now + timedelta(days=config.JWT_REFRESH_EXPIRE_DAYS)
    }
    access = jwt.encode(access_payload, config.JWT_SECRET, algorithm="HS256")
    refresh = jwt.encode(refresh_payload, config.JWT_SECRET, algorithm="HS256")
    return access, refresh

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    try:
        payload = jwt.decode(token, config.JWT_SECRET, algorithms=["HS256"])
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Token inválido")
    except JWTError:
        raise HTTPException(status_code=401, detail="Token inválido")
    user = await db.db.users.find_one({"_id": user_id})
    if not user:
        raise HTTPException(status_code=401, detail="Usuário não encontrado")
    return user

# Novo: dependência reutilizável para checar role=admin
async def admin_required(user=Depends(get_current_user)):
    """
    Dependência para proteger rotas apenas para admins.
    Usa get_current_user e verifica role.
    """
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuário não autenticado")
    if user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required")
    return user
