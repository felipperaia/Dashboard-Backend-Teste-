"""
tasks/scheduler.py
Inicia APScheduler para:
1. Job a cada 5 min: ingesta ThingSpeak
2. Job semanal (segunda-feira 3h UTC): fetch meteorologia por silo
3. Job semanal (domingo 2h UTC): ML training via sparkz/train.py
4. Job DIÁRIO (segunda-feira 4h UTC): ML prediction via sparkz/predict.py ← NOVO
5. Job a cada N minutos: Keep-alive para evitar hibernação no Render free tier
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from .. import config
from ..services.thingspeak import fetchandstore
from ..services.weather import fetchweatherforlocation
from .. import db
import asyncio
import logging
import os
import httpx
import subprocess
from datetime import datetime

logger = logging.getLogger("uvicorn.error")


def start_scheduler(app):
    """Inicia APScheduler com todos os jobs."""
    scheduler = AsyncIOScheduler()

    # ==================== JOB 1: ThingSpeak a cada 5 min ====================
    async def thingspeak_job():
        """Busca dados do ThingSpeak e salva em MongoDB."""
        try:
            for silo_key, channel in config.THINGSPEAK_CHANNELS.items():
                read_key = config.THINGSPEAK_API_KEYS.get(silo_key)
                if not read_key:
                    logger.warning(f"No API key for silo {silo_key}")
                    continue

                # Buscar silo_id e device_id do MongoDB
                silo = await db.db.silos.find_one({"name": silo_key})
                silo_id = silo.get("_id") if silo else None
                device_id = silo.get("device_id") if silo else None

                await fetchandstore(
                    channel_id=channel,
                    read_key=read_key,
                    silo_id=str(silo_id) if silo_id else silo_key,
                    device_id=device_id,
                )
                logger.info(f"ThingSpeak job: fetched channel {channel} for silo {silo_key}")
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
                    logger.info(
                        f"Fetching weather for silo {silo.get('name')} ({lat}, {lon})"
                    )
                    doc = await fetchweatherforlocation(
                        lat=float(lat),
                        lon=float(lon),
                        days=7,
                        silo_id=str(silo.get("_id")),
                    )
                    if doc:
                        logger.info(f"Weather data saved for silo {silo.get('name')}")
                    else:
                        logger.warning(
                            f"Failed to fetch weather for silo {silo.get('name')}"
                        )
        except Exception as e:
            logger.error(f"Error in weekly_weather_job: {e}")

    # Executar segunda-feira (1 = Monday) às 3h UTC
    scheduler.add_job(weekly_weather_job, "cron", day_of_week=1, hour=3)

    # ==================== JOB 3: ML Training semanal (domingo 2h UTC) ====================
    async def weekly_retrain_job():
        """Treina modelos ML via sparkz/train.py em background."""
        try:
            # Comando do treinamento (pode vir de variável de env ou padrão)
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
                logger.info(f"ML train stdout: {out.decode('utf-8', errors='ignore')}")
            if err:
                logger.warning(f"ML train stderr: {err.decode('utf-8', errors='ignore')}")

        except Exception as e:
            logger.error(f"Error in weekly_retrain_job: {e}")

    # Executar domingo (6 = Sunday) às 2h UTC (configurável via env)
    cron_day = os.environ.get("ML_RETRAIN_CRON_DAY", "sun")
    try:
        cron_hour = int(os.environ.get("ML_RETRAIN_CRON_HOUR", "2"))
    except:
        cron_hour = 2
    scheduler.add_job(weekly_retrain_job, "cron", day_of_week=cron_day, hour=cron_hour)

    # ==================== JOB 4: ML Prediction diária (segunda-feira 4h UTC) ← NOVO ====================
    async def daily_predict_job():
        """Executa previsões ML via sparkz/predict.py em background."""
        try:
            # Comando da previsão
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
                logger.warning(
                    f"ML predict stderr: {err.decode('utf-8', errors='ignore')}"
                )

        except Exception as e:
            logger.error(f"Error in daily_predict_job: {e}")

    # Executar segunda-feira (1 = Monday) às 4h UTC (após o train, antes do job de 5h)
    # Ou ajuste conforme necessário; pode ser diário se preferir:
    # scheduler.add_job(daily_predict_job, "cron", hour=4)  # Diário às 4h
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
                    logger.debug(
                        f"Keep-alive ping to {health_url} status {r.status_code}"
                    )
                except Exception as e:
                    logger.warning(f"Keep-alive health ping failed: {e}")

                # Se houver LLM externo, fazer ping também
                llm_url = (
                    os.environ.get("KEEPALIVE_PING_LLM_URL")
                    or os.environ.get("LLM_URL")
                )
                if llm_url:
                    try:
                        r2 = await client.get(llm_url)
                        logger.debug(
                            f"Keep-alive ping to LLM {llm_url} status {r2.status_code}"
                        )
                    except Exception as e:
                        logger.warning(f"Keep-alive LLM ping failed: {e}")

        except Exception as e:
            logger.error(f"Error in keepalive_job: {e}")

    # Executar a cada N minutos (padrão 10, configurável)
    try:
        interval_min = int(os.environ.get("KEEPALIVE_INTERVAL_MIN", "10"))
    except:
        interval_min = 10
    scheduler.add_job(keepalive_job, "interval", minutes=interval_min)

    # ==================== Iniciar scheduler ====================
    scheduler.start()
    logger.info("APScheduler started with all jobs configured")

    return scheduler