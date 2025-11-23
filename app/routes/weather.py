from fastapi import APIRouter, Depends, HTTPException
from .. import db, auth
from ..services.weather import fetch_weather_for_location
from typing import Optional

router = APIRouter()


@router.post("/fetch-weekly")
async def fetch_weekly(lat: float, lon: float, user=Depends(auth.get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin required")
    doc = await fetch_weather_for_location(lat, lon)
    if not doc:
        raise HTTPException(status_code=500, detail="Erro ao buscar previsão")
    return {"status": "ok", "saved": doc}


@router.get("/latest")
async def latest(lat: Optional[float] = None, lon: Optional[float] = None, user=Depends(auth.get_current_user)):
    q = {}
    if lat is not None and lon is not None:
        q = {"lat": float(lat), "lon": float(lon)}
    cur = db.db.meteorology.find(q).sort("fetched_at", -1).limit(10)
    rows = [r async for r in cur]
    return rows
