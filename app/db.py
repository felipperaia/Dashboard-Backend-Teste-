"""
db.py
Inicializa cliente Motor e expõe referências às coleções.
"""
import os
from motor.motor_asyncio import AsyncIOMotorClient
from . import config

DB_NAME = os.getenv("DB_NAME", "silosdb")  # "silosdb" como valor padrão

_client = None
db = None
# Expor collections como variáveis do módulo (serão atribuídas em init_db)
users = None
readings = None
alerts = None
reports = None
push_subscriptions = None
refresh_tokens = None

def init_db():
    global _client, db
    _client = AsyncIOMotorClient(config.MONGO_URI)
    db = _client[DB_NAME]
    # Cria índices básicos
    db.users.create_index("username", unique=True)
    db.readings.create_index([("silo_id", 1), ("timestamp", -1)])
    db.alerts.create_index("silo_id")
    # Índice para subscriptions de push (endpoint deve ser único)
    db.push_subscriptions.create_index("endpoint", unique=True)
    # Índice para refresh tokens (user_id)
    db.refresh_tokens.create_index("user_id")

    # Atribuir coleções como atributos do módulo para acesso direto (ex: db.reports)
    global users, readings, alerts, reports, push_subscriptions, refresh_tokens
    users = db.users
    readings = db.readings
    alerts = db.alerts
    reports = db.reports
    push_subscriptions = db.push_subscriptions
    refresh_tokens = db.refresh_tokens

    return db


def get_collection(name: str):
    """Retorna a coleção do MongoDB com o nome `name`. Faz fallback caso init_db não tenha sido chamado ainda."""
    global db, _client
    if db is None:
        # Tentativa de inicialização preguiçosa
        if config.MONGO_URI:
            init_db()
        else:
            raise RuntimeError("MongoDB não inicializado e MONGO_URI não configurado")
    return db[name]
