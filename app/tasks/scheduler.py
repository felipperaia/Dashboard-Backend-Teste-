"""
tasks/scheduler.py
Inicia APScheduler para rodar job de ingestão ThingSpeak a cada N minutos.
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from .. import config
from ..services.thing_speak import fetch_and_store
from .. import db
import asyncio
from ..services.weather import fetch_weather_for_location
import logging

logger = logging.getLogger("uvicorn.error")

def start_scheduler(app):
    scheduler = AsyncIOScheduler()
    async def job():
        # Para cada channel mapeado em config.THINGSPEAK_CHANNELS
        for silo_key, channel in config.THINGSPEAK_CHANNELS.items():
            read_key = config.THINGSPEAK_API_KEYS.get(silo_key)
            # Mapear silo_key para silo_id na collection silos (device_id ou nome)
            silo = await db.db.silos.find_one({"name": silo_key})
            silo_id = silo["_id"] if silo else None
            device_id = silo.get("device_id") if silo else None
            await fetch_and_store(channel, read_key, silo_id=silo_id, device_id=device_id)
    scheduler.add_job(lambda: asyncio.create_task(job()), "interval", minutes=5)

    # Job semanal para coletar previsões meteorológicas por silo (se tiver lat/lon)
    async def weekly_weather_job():
        try:
            cursor = db.db.silos.find({"location.lat": {"$exists": True}})
            async for s in cursor:
                lat = s.get("location", {}).get("lat")
                lon = s.get("location", {}).get("lon")
                if lat is not None and lon is not None:
                    logger.info(f"Coletando previsão meteorológica para silo {s.get('name')} ({lat},{lon})")
                    await fetch_weather_for_location(float(lat), float(lon))
        except Exception as e:
            logger.error(f"Erro no weekly_weather_job: {e}")

    # adicionar job semanal (uma vez por semana)
    scheduler.add_job(lambda: asyncio.create_task(weekly_weather_job()), "cron", day_of_week="mon", hour=3)
    scheduler.start()
