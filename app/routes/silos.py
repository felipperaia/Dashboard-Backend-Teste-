"""
routes/silos.py
Endpoints para listar e editar silos e seus settings.
CORRIGIDO: Garantir que _id seja convertido para string
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import List
from ..schemas import SiloCreate, SiloSettings
from .. import db, auth
from datetime import datetime
import uuid
import httpx
from fastapi import Body

router = APIRouter()

@router.get("/", response_model=List[dict])
async def list_silos(user=Depends(auth.get_current_user)):
    """
    Lista todos os silos.
    CORREÇÃO: Converter _id para string e garantir estrutura consistente
    """
    cursor = db.db.silos.find({})
    res = []
    async for s in cursor:
        # ✅ CORREÇÃO: Converter ObjectId para string e garantir estrutura consistente
        silo_data = {
            "_id": str(s["_id"]),
            "name": s.get("name", ""),
            "device_id": s.get("device_id", ""),
            "location": s.get("location", {}),
            "settings": s.get("settings", {}),
            "created_at": s.get("created_at"),
            "responsible": s.get("responsible", {})
        }
        res.append(silo_data)
    print(f"✅ Silos retornados: {len(res)}")  # Debug
    return res

@router.post("/", response_model=dict)
async def create_silo(body: SiloCreate, user=Depends(auth.get_current_user)):
    # somente admin
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin required")
    
    # suportar latitude/longitude opcionais
    location = {}
    if getattr(body, 'latitude', None) is not None and getattr(body, 'longitude', None) is not None:
        location = {"lat": body.latitude, "lon": body.longitude}

    doc = {
        "_id": str(uuid.uuid4()),
        "name": body.name,
        "device_id": body.device_id,
        "location": location,
        "settings": body.settings.dict() if body.settings else {},
        "created_at": datetime.utcnow(),
        "responsible": {}
    }
    
    result = await db.db.silos.insert_one(doc)
    print(f"✅ Silo criado: {doc['_id']}")  # Debug
    return {"id": doc["_id"], "status": "created"}


@router.post("/import_thingspeak")
async def import_thingspeak(channel_id: int = Body(..., embed=True), read_key: str = Body(None, embed=True), user=Depends(auth.get_current_user)):
    """Importa metadados de um canal ThingSpeak e cria/atualiza um Silo no banco.
    Body: {"channel_id": 12345, "read_key": "XYZ"}
    """
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin required")

    url = f"https://api.thingspeak.com/channels/{channel_id}.json"
    async with httpx.AsyncClient() as client:
        r = await client.get(url, timeout=10)
    if r.status_code != 200:
        raise HTTPException(status_code=404, detail="Channel not found on ThingSpeak")
    data = r.json()
    # Monta documento do silo
    doc = {
        "_id": str(uuid.uuid4()),
        "name": data.get("name") or f"Channel {channel_id}",
        "device_id": str(channel_id),
        "thingspeak_channel_id": channel_id,
        "thingspeak_read_key": read_key,
        "location": data.get("latitude") and data.get("longitude") and {"lat": data.get("latitude"), "lon": data.get("longitude")} or {},
        "settings": {},
        "created_at": datetime.utcnow(),
        "responsible": {}
    }

    # Upsert por thingspeak_channel_id
    await db.db.silos.update_one({"thingspeak_channel_id": channel_id}, {"$set": doc}, upsert=True)
    return {"status": "ok", "silo_id": doc["_id"]}

@router.put("/{silo_id}/settings", response_model=dict)
async def update_settings(silo_id: str, settings: SiloSettings, user=Depends(auth.get_current_user)):
    if user.get("role") not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Admin or operator required")
    
    result = await db.db.silos.update_one(
        {"_id": silo_id}, 
        {"$set": {"settings": settings.dict()}}
    )
    
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Silo not found")
    
    return {"status": "ok", "message": "Settings updated"}