"""services/weather.py
Serviço para buscar previsões meteorológicas (Open-Meteo gratuito) e salvar no MongoDB semanalmente.
"""
import httpx
from datetime import datetime
from .. import db, config
from ..db import get_collection
import logging

logger = logging.getLogger("uvicorn.error")

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

async def fetch_weather_for_location(lat: float, lon: float, days: int = 7, silo_id: str = None):
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
        "timezone": "UTC"
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(OPEN_METEO_URL, params=params)
        if r.status_code != 200:
            logger.error(f"Open-Meteo error: {r.status_code} {r.text}")
            return None
        data = r.json()
        # Save summary
        doc = {
            "_id": f"met_{lat}_{lon}_{int(datetime.utcnow().timestamp())}",
            "lat": lat,
            "lon": lon,
            "silo_id": silo_id,
            "fetched_at": datetime.utcnow(),
            "data": data
        }
        met_coll = get_collection('meteorology')
        await met_coll.insert_one(doc)
        return doc
    except Exception as e:
        logger.error(f"Erro ao buscar Open-Meteo: {e}")
        return None
