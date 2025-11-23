"""
routes/readings.py
Endpoints para inserir e listar leituras.
Após inserção chama pipeline de regras e ML.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
from ..schemas import ReadingIn
from .. import db, auth
from datetime import datetime
import uuid
from ..services import notification
from ..utils import apply_threshold_rules
import logging

router = APIRouter()
logger = logging.getLogger("uvicorn.error")

@router.get("/", response_model=List[dict])
async def list_readings(
    silo_id: Optional[str] = Query(None, description="Filtrar por ID do silo"),
    limit: int = Query(100, description="Número máximo de leituras a retornar"),
    user=Depends(auth.get_current_user)
):
    """
    Lista leituras com filtros opcionais por silo_id.
    """
    query = {}
    if silo_id:
        query["silo_id"] = silo_id
    
    cursor = db.db.readings.find(query).sort("timestamp", -1).limit(limit)
    readings = []
    async for reading in cursor:
        # Converter ObjectId para string
        reading["_id"] = str(reading["_id"])
        readings.append(reading)
    
    return readings

@router.post("/", response_model=dict)
async def create_reading(body: ReadingIn, user=Depends(auth.get_current_user)):
    doc = body.dict()
    doc["_id"] = str(uuid.uuid4())
    doc["timestamp"] = doc["timestamp"]
    await db.db.readings.insert_one(doc)

    # Regras determinísticas
    alerts = await apply_threshold_rules(doc)

    # ML anomaly detection (import lazy para evitar circular imports)
    is_anom = False
    score = None
    try:
        from ..ml.model import detect_anomaly  # import lazy
        try:
            is_anom, score = await detect_anomaly(doc)
        except Exception as e:
            # Se o ML falhar em runtime, logamos e seguimos sem bloquear.
            logger.warning("Erro ao executar detect_anomaly: %s", e)
            is_anom, score = False, None
    except Exception as e:
        # Se não for possível importar (por ex. import circular), logamos e seguimos.
        logger.warning("Não foi possível importar app.ml.model.detect_anomaly: %s", e)
        is_anom, score = False, None

    if is_anom:
        alerts.append({"level": "warning", "message": "Anomalia detectada", "value": score})

    # Salvar alerts e notificar
    for a in alerts:
        a_doc = {
            "_id": str(uuid.uuid4()),
            "silo_id": doc.get("silo_id"),
            "level": a.get("level", "critical"),
            "message": a.get("message"),
            "value": a.get("value"),
            "timestamp": datetime.utcnow(),
            "acknowledged": False,
        }
        await db.db.alerts.insert_one(a_doc)
        await notification.notify_alert(a_doc)
    return {"status": "ok"}