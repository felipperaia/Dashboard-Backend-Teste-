from fastapi import FastAPI
import logging
from fastapi.middleware.cors import CORSMiddleware
import asyncio

# Importar módulo db para inicialização do banco
from . import db

# Importar routers existentes na pasta routes
from .routes import auth, users, silos, readings, alerts, notifications
from .routes import chat
from .routes import mfa
from .routes import rag, weather, reports

# Importar o poller
from .services.thingspeak_poller import thingspeak_poller
from .tasks.scheduler import start_scheduler

app = FastAPI()
logger = logging.getLogger("uvicorn.error")

# ✅ CORREÇÃO CORS - PERMITIR TODAS AS ORIGENS DO FRONTEND
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://dashboardsilo.netlify.app",
        "https://splendorous-dusk-f86c65.netlify.app",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173", 
        "http://127.0.0.1:5173"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Evento de startup para inicializar o banco de dados e iniciar o poller
@app.on_event("startup")
async def startup_event():
    db.init_db()
    logger.info("Database initialized")
    
    # Iniciar o poller do ThingSpeak em segundo plano
    asyncio.create_task(thingspeak_poller())
    logger.info("ThingSpeak poller started")

    # Iniciar scheduler (APScheduler) para jobs periódicos (ex: coleta semanal do tempo)
    try:
        start_scheduler(app)
        logger.info("Scheduler started")
    except Exception as e:
        logger.warning(f"Falha ao iniciar scheduler: {e}")

# Registrar routers principais
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(users.router, prefix="/api/users", tags=["users"])
app.include_router(silos.router, prefix="/api/silos", tags=["silos"])
app.include_router(readings.router, prefix="/api/readings", tags=["readings"])
app.include_router(alerts.router, prefix="/api/alerts", tags=["alerts"])
app.include_router(notifications.router, prefix="/api/notifications", tags=["notifications"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(mfa.router, prefix="/api/mfa", tags=["mfa"])
app.include_router(rag.router, prefix="/api/rag", tags=["rag"])
app.include_router(weather.router, prefix="/api/weather", tags=["weather"])
app.include_router(reports.router, prefix="/api/reports", tags=["reports"])

# Tentar registrar router ML de forma condicional:
try:
    try:
        from .routes import ml as ml_routes
        if hasattr(ml_routes, "router"):
            app.include_router(ml_routes.router, prefix="/api/ml", tags=["ml"])
        else:
            logger.info("app.routes.ml foi importado mas nao tem atributo 'router'; pulando.")
    except ImportError:
        from . import ml as ml_pkg
        if hasattr(ml_pkg, "router"):
            app.include_router(ml_pkg.router, prefix="/api/ml", tags=["ml"])
        else:
            logger.info("app.ml importado mas nao tem atributo 'router'; pulando registro do router ML.")
except Exception as e:
    logger.warning("Nao foi possivel registrar router ML: %s", e)

