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

def init_db():
    global _client, db
    _client = AsyncIOMotorClient(config.MONGO_URI)
    db = _client["silosdb"]
    # Cria índices básicos
    db.users.create_index("username", unique=True)
    db.readings.create_index([("silo_id", 1), ("timestamp", -1)])
    db.alerts.create_index("silo_id")
    # Índice para subscriptions de push (endpoint deve ser único)
    db.push_subscriptions.create_index("endpoint", unique=True)
    # Índice para refresh tokens (user_id)
    db.refresh_tokens.create_index("user_id")
    return db
