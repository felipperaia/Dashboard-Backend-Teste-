from typing import List, Dict, Any, Optional
from datetime import datetime
from pydantic import BaseModel, Field


class Thresholds(BaseModel):
    """Limites para alertas de leituras."""
    max_temp: Optional[float] = None
    max_humidity: Optional[float] = None
    max_gas: Optional[float] = None


class NotificationTemplates(BaseModel):
    """Templates para cada canal de notificação."""
    email_subject: Optional[str] = None
    email_body: Optional[str] = None
    sms_body: Optional[str] = None
    telegram_text: Optional[str] = None
    telegram_parse_mode: Optional[str] = None  # "Markdown" | "HTML" | None
    popup_text: Optional[str] = None


class SiloIn(BaseModel):
    """Dados de input para criar/atualizar silo."""
    name: str
    thingspeak_channel_id: Optional[int] = None
    thingspeak_read_key: Optional[str] = None
    thresholds: Optional[Thresholds] = None
    notify_email: Optional[bool] = True
    notify_sms: Optional[bool] = False
    notify_telegram: Optional[bool] = False
    email_to: Optional[str] = None
    sms_to: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    templates: Optional[NotificationTemplates] = None


class Silo(SiloIn):
    """Silo completo (com id)."""
    id: str = Field(..., alias="_id")


class Reading(BaseModel):
    """Leitura de sensores."""
    silo_id: str
    timestamp: datetime
    temperature: Optional[float] = None
    humidity: Optional[float] = None
    gas: Optional[float] = None
    # Luminosity fields
    luminosity_alert: Optional[int] = None  # 1 = alerta (ex: possível fogo / brilho inesperado)
    lux: Optional[float] = None
    raw: Dict[str, Any] = {}


class SiloEvent(BaseModel):
    """Eventos relacionados ao silo (ex: abertura, fechamento, incêndio detectado)."""
    silo_id: str
    event_type: str
    payload: Dict[str, Any] = {}
    timestamp: datetime = Field(default_factory=lambda: datetime.utcnow())


class Alert(BaseModel):
    """Alerta persistido no banco."""
    silo_id: str
    message: str
    level: str = "warning"
    created_at: datetime = Field(default_factory=lambda: datetime.utcnow())
    channels: List[str] = []


class ReportIn(BaseModel):
    """Input para criar relatório."""
    silo_id: str
    start: datetime
    end: datetime
    title: Optional[str] = None
    notes: Optional[str] = None


class ReportMetrics(BaseModel):
    """Métricas calculadas para um relatório."""
    min: Optional[float] = None
    max: Optional[float] = None
    avg: Optional[float] = None
    count: int = 0
    std_dev: Optional[float] = None  # desvio padrão
    p25: Optional[float] = None  # percentil 25
    p50: Optional[float] = None  # mediana
    p75: Optional[float] = None  # percentil 75


class Report(ReportIn):
    """Relatório completo (métricas + input)."""
    id: str = Field(..., alias="_id")
    silo_name: str  # nome do silo no momento da geração
    metrics: Dict[str, Any]  # temperatura/umidade/gas -> ReportMetrics
    created_at: datetime = Field(default_factory=lambda: datetime.utcnow())


class ChatMessage(BaseModel):
    """Mensagem individual do chat."""
    role: str
    content: str


class ChatRequest(BaseModel):
    """Request body para /chat."""
    messages: List[ChatMessage]
    silo_id: Optional[str] = None  # opcional: inclui dados do silo
    include_recent: int = 0  # se >0, inclui N leituras recentes do silo no contexto