"""
config.py
Lê variáveis de ambiente e centraliza configurações do app.
"""
import os
import json
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME", "silosdb")
JWT_SECRET = os.getenv("JWT_SECRET", "dev_secret")
JWT_ACCESS_EXPIRE_MIN = int(os.getenv("JWT_ACCESS_EXPIRE_MIN", "15"))
JWT_REFRESH_EXPIRE_DAYS = int(os.getenv("JWT_REFRESH_EXPIRE_DAYS", "7"))
INIT_ADMIN_SECRET = os.getenv("INIT_ADMIN_SECRET")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY")
THINGSPEAK_API_KEYS = json.loads(os.getenv("THINGSPEAK_API_KEYS", "{}"))
THINGSPEAK_CHANNELS = json.loads(os.getenv("THINGSPEAK_CHANNELS", "{}"))
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT") or 0)
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
SMTP_FROM = os.getenv("SMTP_FROM")

# Twilio
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_FROM = os.getenv("TWILIO_FROM")

# OpenRouter (LLM)
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
# Preferir modelo estável 'openai/gpt-oss-20b:free' por padrão (deepseek indisponível)
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-oss-20b:free")
LLM_SYSTEM_PROMPT = os.getenv("LLM_SYSTEM_PROMPT", "Você é um assistente especializado no sistema de monitoramento de silos de soja."
    "Responda apenas sobre o sistema atual, seus dados, funcionalidades e uso, usando a documentação disponível."
    "Explique o que o usuário pode fazer no dashboard e como interpretar leituras de umidade, temperatura e gases."
    "Não fale de assuntos fora do sistema que não sejam relevantes para o monitoramento de silos.")

# Habilitar RAG (retrieval-augmented generation) por padrão — permite anexar contexto do DB e relatórios
USE_RAG = os.getenv('USE_RAG', 'true').lower() in ('1', 'true', 'yes')

# Lista de modelos fallback (comma-separated) para tentar caso o modelo principal falhe
FALLBACK_OPENROUTER_MODELS = [m.strip() for m in os.getenv('FALLBACK_OPENROUTER_MODELS', 'openai/gpt-oss-20b:free,deepseek/deepseek-chat-v3.1:free').split(',') if m.strip()]

# Luminosity thresholds (lux)
# Defaults: ambiente escuro/fechado até ~10 lux, aberto/iluminado acima ~100 lux
# Podem ser sobrescritos via variáveis de ambiente
LUMINOSITY_DARK_THRESHOLD = float(os.getenv("LUMINOSITY_DARK_THRESHOLD", "10"))
LUMINOSITY_OPEN_THRESHOLD = float(os.getenv("LUMINOSITY_OPEN_THRESHOLD", "100"))

# Tempo mínimo para aceitar leituras idênticas (em segundos) antes de gravar duplicatas
# default: 5 horas = 18000 segundos
IDENTICAL_READINGS_MIN_SECONDS = int(os.getenv("IDENTICAL_READINGS_MIN_SECONDS", "18000"))
