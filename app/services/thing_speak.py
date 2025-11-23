"""
services/thing_speak.py
Cliente simples para ThingSpeak: consulta feeds e converte para ReadingIn.
"""
import httpx
from .. import config, db
import logging
from datetime import datetime
import uuid

logger = logging.getLogger("uvicorn.error")
THINGSPEAK_URL = "https://api.thingspeak.com/channels/{channel}/feeds.json?api_key={key}"

async def fetch_and_store(channel_id: int, read_key: str, silo_id: str = None, device_id: str = None):
    logger.info(f"Buscando dados do ThingSpeak para o canal {channel_id}")
    url = THINGSPEAK_URL.format(channel=channel_id, key=read_key)
    
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(url, timeout=10.0)
        
        if r.status_code != 200:
            logger.error(f"Erro ao buscar dados: Status {r.status_code}")
            return
        
        data = r.json()
        feeds = data.get("feeds", [])
        
        if not feeds:
            logger.info("Nenhum dado encontrado no feed")
            return
        
        f = feeds[0]
        logger.info(f"Dados recebidos: {f}")

        # Map fields -> readings
        try:
            # Map fields (tentar ser tolerante a ausência de campos)
            temp = float(f.get("field1") or 0.0)
            rh = float(f.get("field2") or 0.0)
            co2 = None
            try:
                co2 = float(f.get("field3")) if f.get("field3") is not None else None
            except Exception:
                co2 = None
            mq2 = None
            try:
                mq2 = int(f.get("field4")) if f.get("field4") is not None else None
            except Exception:
                mq2 = None

            # Luminosity fields (field5 = boolean/flag, field6 = lux value) — adapt conforme necessário
            luminosity_alert = None
            lux = None
            try:
                if f.get("field5") is not None:
                    luminosity_alert = int(f.get("field5"))
            except Exception:
                luminosity_alert = None
            try:
                if f.get("field6") is not None:
                    lux = float(f.get("field6"))
            except Exception:
                lux = None

            doc = {
                "_id": str(uuid.uuid4()),
                "device_id": device_id or f.get("entry_id"),
                "timestamp": datetime.strptime(f.get("created_at"), "%Y-%m-%dT%H:%M:%SZ"),
                "temp_C": temp,
                "rh_pct": rh,
                "co2_ppm_est": co2,
                "mq2_raw": mq2,
                "luminosity_alert": luminosity_alert,
                "lux": lux,
                "device_status": "ok",
                "silo_id": silo_id,
                "raw": f
            }
        except Exception as e:
            logger.error(f"Erro ao processar dados do ThingSpeak: {e}")
            return

        # Evitar duplicatas: comparar com última leitura do mesmo silo
        try:
            last = await db.db.readings.find({"silo_id": silo_id}).sort("timestamp", -1).limit(1).to_list(1)
            if last:
                last = last[0]
                fields_to_compare = ["temp_C", "rh_pct", "co2_ppm_est", "mq2_raw", "luminosity_alert", "lux"]
                identical = True
                for k in fields_to_compare:
                    # usar None-safe comparison (floats comparados diretamente — aceitável para leituras discretas)
                    if (last.get(k) is None and doc.get(k) is not None) or (last.get(k) is not None and doc.get(k) is None):
                        identical = False
                        break
                    if last.get(k) is not None and doc.get(k) is not None:
                        if isinstance(doc.get(k), float):
                            # diferença pequena aceitável? usar igualdade direta, manter simples
                            if float(last.get(k)) != float(doc.get(k)):
                                identical = False
                                break
                        else:
                            if last.get(k) != doc.get(k):
                                identical = False
                                break

                if identical:
                    # verificar tempo desde a última leitura idêntica
                    last_ts = last.get("timestamp")
                    if isinstance(last_ts, str):
                        try:
                            from dateutil import parser as _parser
                            last_ts_dt = _parser.parse(last_ts)
                        except Exception:
                            last_ts_dt = None
                    else:
                        last_ts_dt = last_ts

                    if last_ts_dt:
                        delta = (doc["timestamp"] - last_ts_dt).total_seconds()
                        if delta < config.IDENTICAL_READINGS_MIN_SECONDS:
                            logger.info(f"Ignorando leitura idêntica recente para silo {silo_id} (delta {delta}s)")
                            return

        except Exception as e:
            logger.warning(f"Não foi possível verificar última leitura para duplicação: {e}")

        # Inserir leitura
        await db.db.readings.insert_one(doc)
        logger.info(f"Dados inseridos no MongoDB: {doc['_id']}")

        # Checar eventos de luminosidade (abertura do silo / possível fogo)
        try:
            # obter estado anterior de lux (se disponível) — usar 'last' obtido antes da inserção
            prev_lux = None
            try:
                if 'last' in locals() and last:
                    prev_lux = last.get("lux")
            except Exception:
                prev_lux = None

            # se lux transitar de <= dark para >= open -> evento de abertura
            if prev_lux is not None and doc.get("lux") is not None:
                if prev_lux <= config.LUMINOSITY_DARK_THRESHOLD and doc.get("lux") >= config.LUMINOSITY_OPEN_THRESHOLD:
                    # registrar evento
                    event = {
                        "_id": str(uuid.uuid4()),
                        "silo_id": silo_id,
                        "event_type": "silo_opened",
                        "payload": {"prev_lux": prev_lux, "lux": doc.get("lux")},
                        "timestamp": datetime.utcnow()
                    }
                    await db.db.silo_events.insert_one(event)
                    # criar alerta visual
                    a_doc = {
                        "_id": str(uuid.uuid4()),
                        "silo_id": silo_id,
                        "level": "warning",
                        "message": "Silo aberto: mudança de luminosidade detectada (possível manutenção)",
                        "value": {"prev_lux": prev_lux, "lux": doc.get("lux")},
                        "timestamp": datetime.utcnow(),
                        "acknowledged": False,
                    }
                    await db.db.alerts.insert_one(a_doc)
            # se luminosity_alert == 1 -> alerta crítico imediato
            if doc.get("luminosity_alert") == 1:
                a_doc = {
                    "_id": str(uuid.uuid4()),
                    "silo_id": silo_id,
                    "level": "critical",
                    "message": "Alerta de luminosidade detectado (possível fogo no silo)",
                    "value": {"lux": doc.get("lux"), "flag": doc.get("luminosity_alert")},
                    "timestamp": datetime.utcnow(),
                    "acknowledged": False,
                }
                await db.db.alerts.insert_one(a_doc)

        except Exception as e:
            logger.error(f"Erro ao processar eventos de luminosidade: {e}")
        
        # Pós-processamento: regras + ML (opcional) + notificações
        try:
            from ..utils import apply_threshold_rules
            from ..services.notification import notify_alert

            # import ML optionalmente
            detect_anomaly = None
            try:
                from ..ml.model import detect_anomaly as _detect_anomaly
                detect_anomaly = _detect_anomaly
            except ImportError:
                # ML não está presente no ambiente — isso é esperado em alguns deployments
                logger.info("ML module not found, skipping anomaly detection")

            alerts = []
            try:
                alerts = await apply_threshold_rules(doc)
            except Exception as e:
                logger.error(f"Erro ao aplicar regras de threshold: {e}")

            if detect_anomaly is not None:
                try:
                    is_anom, score = await detect_anomaly(doc)
                    if is_anom:
                        alerts.append({"level": "warning", "message": "Anomalia detectada (ML)", "value": score})
                except Exception as e:
                    logger.error(f"Erro na detecção de anomalias (ML): {e}")

            for a in alerts:
                try:
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
                    await notify_alert(a_doc)
                except Exception as e:
                    logger.error(f"Erro ao gravar/enviar alert: {e}")

        except ImportError as e:
            # módulos essenciais do pós-processamento ausentes — registrar como info
            logger.info(f"Pós-processamento parcialmente desativado: {e}")
        except Exception as e:
            logger.error(f"Erro no pós-processamento: {e}")
            
    except Exception as e:
        logger.error(f"Erro na requisição para ThingSpeak: {e}")