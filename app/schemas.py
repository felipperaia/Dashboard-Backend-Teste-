"""
schemas.py
Modelos Pydantic para requests/responses.
"""
from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List, Dict, Any
from enum import Enum
from datetime import datetime

class Token(BaseModel):
    access_token: str
    refresh_token: str

class RoleEnum(str, Enum):
    admin = "admin"
    operator = "operator"


class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str
    role: RoleEnum = RoleEnum.operator
    phone: Optional[str] = None

class UserOut(BaseModel):
    id: str
    username: str
    email: EmailStr
    role: str
    created_at: datetime
    phone: Optional[str] = None

class UserUpdate(BaseModel):
     """Schema para atualização do perfil do usuário"""
     name: Optional[str] = None
     email: Optional[EmailStr] = None
     phone: Optional[str] = None

class LoginIn(BaseModel):
    username: str
    password: str

class SiloSettings(BaseModel):
    temp_threshold: Optional[float] = None
    co2_threshold: Optional[float] = None
    mq2_threshold: Optional[int] = None
    alert_interval_min: Optional[int] = 5

class SiloCreate(BaseModel):
    name: str
    device_id: str
    # location agora separada em latitude/longitude opcionais
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    settings: Optional[SiloSettings] = None

class ReadingIn(BaseModel):
    device_id: str
    timestamp: datetime
    temp_C: float
    rh_pct: float
    co2_ppm_est: Optional[float] = None
    mq2_raw: Optional[int] = None
    # Luminosity: boolean-like flag (1 = possível fogo/abertura) e lux (lumens)
    luminosity_alert: Optional[int] = None  # 1 or 0 (ThingSpeak often sends ints)
    lux: Optional[float] = None
    device_status: Optional[str] = "ok"
    silo_id: Optional[str] = None

class AlertOut(BaseModel):
    id: str
    silo_id: str
    level: str
    message: str
    value: Any
    timestamp: datetime
    acknowledged: bool


class ForecastOut(BaseModel):
    id: Optional[str]
    siloId: str
    target: str
    timestamp_forecast: datetime
    value_predicted: float
    horizon_hours: int
    generated_at: Optional[datetime]
