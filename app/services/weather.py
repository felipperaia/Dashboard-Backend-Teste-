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
        "current_weather": True,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
        "hourly": "temperature_2m,relativehumidity_2m,apparent_temperature",
        "timezone": "America/Sao_Paulo",
        "forecast_days": days,
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(OPEN_METEO_URL, params=params)
        if r.status_code != 200:
            logger.error(f"Open-Meteo error: {r.status_code} {r.text}")
            return None
        data = r.json()
        # build a convenient summary for frontend
        daily = data.get('daily', {})
        current = data.get('current_weather', {})

        summary = {
            'current_temp': current.get('temperature'),
            'current_windspeed': current.get('windspeed'),
            'current_weathercode': current.get('weathercode'),
            'dates': daily.get('time', []),
            'temp_max': daily.get('temperature_2m_max', []),
            'temp_min': daily.get('temperature_2m_min', []),
            'precipitation_sum': daily.get('precipitation_sum', []),
        }
        # Save summary
        doc = {
            "_id": f"met_{lat}_{lon}_{int(datetime.utcnow().timestamp())}",
            "lat": lat,
            "lon": lon,
            "silo_id": silo_id,
            "fetched_at": datetime.utcnow(),
            "data": data,
            "summary": summary,
        }
        met_coll = get_collection('meteorology')
        await met_coll.insert_one(doc)
        return doc
    except Exception as e:
        logger.error(f"Erro ao buscar Open-Meteo: {e}")
        return None
