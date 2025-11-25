"""
tasks/scheduler.py
Inicia APScheduler para:
1. Job a cada 5 min: ingesta ThingSpeak
2. Job semanal (segunda-feira 3h UTC): fetch meteorologia por silo
3. Job semanal (domingo 2h UTC): ML training via sparkz/train.py
4. Job DIÁRIO (segunda-feira 4h UTC): ML prediction via sparkz/predict.py
5. Job a cada N minutos: Keep-alive para evitar hibernação no Render free tier
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from .. import config
from .. import db
from ..services.weather import fetchweatherforlocation
from ..services.thing_speak import fetch_and_store  # <- CORRETO
import logging
import os
import httpx
import subprocess

logger = logging.getLogger("uvicorn.error")


def start_scheduler(app):
    """Inicia APScheduler com todos os jobs."""
    scheduler = AsyncIOScheduler()

    # ==================== JOB 1: ThingSpeak a cada 5 min ====================
    async def thingspeak_job():
        """Busca dados do ThingSpeak e salva em MongoDB."""
        try:
            # Usa os mapeamentos THINGSPEAK_CHANNELS e THINGSPEAK_API_KEYS do config
            if not getattr(config, "THINGSPEAK_CHANNELS", None) or not getattr(
                config, "THINGSPEAK_API_KEYS", None
            ):
                logger.warning("THINGSPEAK_CHANNELS ou THINGSPEAK_API_KEYS não configurados")
                return

            for system_channel_id, thing_channel_id in config.THINGSPEAK_CHANNELS.items():
                read_key = config.THINGSPEAK_API_KEYS.get(system_channel_id)
                if not read_key:
                    logger.warning(f"Nenhuma API key para o canal lógico {system_channel_id}")
                    continue

                # Opcional: buscar device_id no MongoDB, se houver
                silo = await db.db.silos.find_one({"_id": system_channel_id}) or await db.db.silos.find_one(
                    {"name": system_channel_id}
                )
                device_id = silo.get("device_id") if silo else None

                await fetch_and_store(
                    channel_id=thing_channel_id,    # ID real do canal no ThingSpeak
                    read_key=read_key,
                    silo_id=str(system_channel_id), # ID lógico do silo no sistema
                    device_id=device_id,
                )
                logger.info(
                    f"ThingSpeak job: fetched channel {thing_channel_id} for silo {system_channel_id}"
                )
        except Exception as e:
            logger.error(f"Error in thingspeak_job: {e}")

    scheduler.add_job(thingspeak_job, "interval", minutes=5)

    # ==================== JOB 2: Meteorologia semanal (segunda-feira 3h UTC) ====================
    async def weekly_weather_job():
        """Busca previsão meteorológica para cada silo com lat/lon."""
        try:
            cursor = db.db.silos.find({"location.lat": {"$exists": True}})
            async for silo in cursor:
                lat = silo.get("location", {}).get("lat")
                lon = silo.get("location", {}).get("lon")

                if lat is not None and lon is not None:
                    logger.info(f"Coletando previsão meteorológica para silo {silo.get('name')} {lat},{lon}")
                    doc = await fetchweatherforlocation(
                        lat=float(lat),
                        lon=float(lon),
                        days=7,
                        silo_id=str(silo.get("_id")),
                    )
                    if doc:
                        logger.info(f"Weather data saved for silo {silo.get('name')}")
                    else:
                        logger.warning(f"Failed to fetch weather for silo {silo.get('name')}")
        except Exception as e:
            logger.error(f"Error in weekly_weather_job: {e}")

    # Executar segunda-feira (1 = Monday) às 3h UTC
    scheduler.add_job(weekly_weather_job, "cron", day_of_week=1, hour=3)

    # ==================== JOB 3: ML Training semanal (domingo 2h UTC) ====================
    async def weekly_retrain_job():
        """Treina modelos ML via sparkz/train.py em background."""
        try:
            train_cmd = os.environ.get("ML_TRAIN_COMMAND") or (
                f"{os.environ.get('PYSPARK_PYTHON', 'python')} sparkz/train.py "
                "--horizons 1,3,24 --targets temperature,humidity,co2,flammable_gases"
            )

            logger.info(f"Starting ML training: {train_cmd}")
            proc = subprocess.Popen(
                train_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=os.environ,
                shell=True,
            )
            out, err = proc.communicate()

            if out:
                logger.info(f"ML weekly retrain stdout: {out.decode('utf-8', errors='ignore')}")
            if err:
                logger.warning(f"ML weekly retrain stderr: {err.decode('utf-8', errors='ignore')}")

        except Exception as e:
            logger.error(f"Error in weekly_retrain_job: {e}")

    cron_day = os.environ.get("ML_RETRAIN_CRON_DAY", "sun")
    try:
        cron_hour = int(os.environ.get("ML_RETRAIN_CRON_HOUR", "2"))
    except Exception:
        cron_hour = 2
    scheduler.add_job(weekly_retrain_job, "cron", day_of_week=cron_day, hour=cron_hour)

    # ==================== JOB 4: ML Prediction diária (segunda-feira 4h UTC) ====================
    async def daily_predict_job():
        """Executa previsões ML via sparkz/predict.py em background."""
        try:
            predict_cmd = os.environ.get("ML_PREDICT_COMMAND") or (
                f"{os.environ.get('PYSPARK_PYTHON', 'python')} sparkz/predict.py "
                "--horizons 1,3,24 --targets temperature,humidity,co2,flammable_gases"
            )

            logger.info(f"Starting ML prediction: {predict_cmd}")
            proc = subprocess.Popen(
                predict_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=os.environ,
                shell=True,
            )
            out, err = proc.communicate()

            if out:
                logger.info(f"ML predict stdout: {out.decode('utf-8', errors='ignore')}")
            if err:
                logger.warning(f"ML predict stderr: {err.decode('utf-8', errors='ignore')}")

        except Exception as e:
            logger.error(f"Error in daily_predict_job: {e}")

    # Pode trocar para diário se quiser: scheduler.add_job(daily_predict_job, "cron", hour=4)
    scheduler.add_job(daily_predict_job, "cron", day_of_week=1, hour=4)

    # ==================== JOB 5: Keep-Alive para Render free tier ====================
    async def keepalive_job():
        """Faz ping no próprio endpoint de health + LLM (se configurado) para evitar hibernação."""
        try:
            base = (
                os.environ.get("KEEPALIVE_PING_URL")
                or os.environ.get("APP_BASE_URL")
                or "http://localhost:8000"
            )
            health_url = f"{base.rstrip('/')}/health"

            async with httpx.AsyncClient(timeout=10.0) as client:
                try:
                    r = await client.get(health_url)
                    logger.debug(f"Keep-alive ping to {health_url} status {r.status_code}")
                except Exception as e:
                    logger.warning(f"Keep-alive health ping failed: {e}")

                llm_url = os.environ.get("KEEPALIVE_PING_LLM_URL") or os.environ.get("LLM_URL")
                if llm_url:
                    try:
                        r2 = await client.get(llm_url)
                        logger.debug(f"Keep-alive ping to LLM {llm_url} status {r2.status_code}")
                    except Exception as e:
                        logger.warning(f"Keep-alive LLM ping failed: {e}")

        except Exception as e:
            logger.error(f"Error in keepalive_job: {e}")

    try:
        interval_min = int(os.environ.get("KEEPALIVE_INTERVAL_MIN", "10"))
    except Exception:
        interval_min = 10
    scheduler.add_job(keepalive_job, "interval", minutes=interval_min)

    # ==================== Iniciar scheduler ====================
    scheduler.start()
    logger.info("APScheduler started with all jobs configured")

    return scheduler
