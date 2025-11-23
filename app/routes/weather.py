from fastapi import APIRouter, Depends, HTTPException
from .. import db, auth
from ..services.weather import fetch_weather_for_location
from ..db import get_collection
from typing import Optional

router = APIRouter()


@router.post("/fetch-weekly")
async def fetch_weekly(lat: float = None, lon: float = None, silo_id: Optional[str] = None, user=Depends(auth.get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin required")
    if silo_id and (not lat or not lon):
        # try to resolve silo location
        silos_coll = get_collection('silos')
        silo = await silos_coll.find_one({"_id": silo_id})
        if silo:
            loc = silo.get('location') or {}
            lat = loc.get('lat') or loc.get('latitude')
            lon = loc.get('lon') or loc.get('longitude')

    if not lat or not lon:
        raise HTTPException(status_code=400, detail="lat/lon ou silo_id com localização requerida")

    doc = await fetch_weather_for_location(float(lat), float(lon), silo_id=silo_id)
    if not doc:
        raise HTTPException(status_code=500, detail="Erro ao buscar previsão")
    return {"status": "ok", "saved": doc}


@router.get("/latest")
async def latest(lat: Optional[float] = None, lon: Optional[float] = None, silo_id: Optional[str] = None, user=Depends(auth.get_current_user)):
    q = {}
    if silo_id:
        q['silo_id'] = silo_id
    elif lat is not None and lon is not None:
        q = {"lat": float(lat), "lon": float(lon)}
    met_coll = get_collection('meteorology')
    cur = met_coll.find(q).sort("fetched_at", -1).limit(10)
    rows = [r async for r in cur]
    return rows
