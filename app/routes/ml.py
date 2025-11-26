"""
routes/ml.py
Endpoints para previsão (forecast) e re-treino via Sparkz.
"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from typing import Optional
from .. import db, auth
from ..db import get_collection
from ..services import ml_service
import subprocess
import os
from datetime import datetime, timedelta

router = APIRouter()


@router.get('/forecast')
async def get_forecast(siloId: Optional[str] = None, target: Optional[str] = None, period_days: int = 7, user=Depends(auth.get_current_user)):
    """Retorna previsões da coleção `forecast_demeter`.
    Query params:
      - siloId: opcional
      - target: opcional (ex: temperature)
      - period_days: período futuro a retornar
    """
    q = {}
    if siloId:
        q['siloId'] = siloId
    if target:
        q['target'] = target
    now = datetime.utcnow()
    end = now + timedelta(days=period_days)
    q['timestamp_forecast'] = {'$gte': now, '$lte': end}
    fc = get_collection('forecast_demeter')
    cursor = fc.find(q).sort('timestamp_forecast', 1)
    res = []
    async for doc in cursor:
        doc['_id'] = str(doc.get('_id'))
        res.append(doc)
    return res


@router.get('/forecast/text')
async def get_forecast_text(siloId: str, period_days: int = 7, user=Depends(auth.get_current_user)):
    """Gera um resumo textual explicativo a partir das previsões e histórico recente."""
    # Busca previsões e leituras recentes e delega para ml_service
    fc = get_collection('forecast_demeter')
    forecasts_cursor = fc.find({'siloId': siloId}).sort('timestamp_forecast', 1)
    forecasts = []
    async for f in forecasts_cursor:
        forecasts.append(f)
    readings_coll = get_collection('readings')
    recent_cursor = readings_coll.find({'silo_id': siloId}).sort('timestamp', -1).limit(200)
    recent = []
    async for r in recent_cursor:
        recent.append(r)
    meteorology_coll = get_collection('meteorology')
    weather_cursor = meteorology_coll.find({'silo_id': siloId}).sort('fetched_at', -1).limit(20)
    weather = []
    async for w in weather_cursor:
        weather.append(w)

    text = ml_service.generate_explanation_text(forecasts, recent, weather)
    return {'siloId': siloId, 'text': text}


@router.post('/forecast/retrain')
async def retrain_model(background_tasks: BackgroundTasks, horizons: Optional[str] = '1,3,24', targets: Optional[str] = 'temperature,humidity,co2,flammable_gases', user=Depends(auth.admin_required)):
    """Dispara um re-treino no Sparkz. Apenas admin pode chamar.
    Dispara em background e retorna status inicial.
    """
    # Monta comando. O ambiente Spark deve estar configurado (SPARK_HOME / spark-submit)
    # Use configured ML_TRAIN_COMMAND if provided (allows spark-submit usage)
    train_cmd = os.environ.get('ML_TRAIN_COMMAND') or f"{os.environ.get('PYSPARK_PYTHON','python')} sparkz/train.py --horizons {horizons} --targets {targets}"

    def run_train():
        try:
            # Run as a shell command so users can configure spark-submit in ML_TRAIN_COMMAND
            proc = subprocess.Popen(train_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=os.environ, shell=True)
            out, err = proc.communicate()
            print('Train stdout:', out.decode('utf-8', errors='ignore'))
            if err:
                print('Train stderr:', err.decode('utf-8', errors='ignore'))
        except Exception as e:
            print('Error running train:', e)

    background_tasks.add_task(run_train)
    return {'status': 'started', 'cmd': train_cmd}


@router.get('/analysis')
async def analysis(siloId: str, period_days: int = 30, user=Depends(auth.get_current_user)):
    """Retorna métricas descritivas e previsões agrupadas para um silo.
    Response:
      - metrics: { temperature: {avg,p50,min,max,count}, humidity: {...}, gas: {...} }
      - forecasts: lista de forecasts (cada item contém target, timestamp_forecast, value_predicted, horizon_hours)
      - explanation: texto gerado a partir de previsões/histórico
    """
    from statistics import mean, median
    fc = get_collection('forecast_demeter')
    readings_coll = get_collection('readings')
    meteorology_coll = get_collection('meteorology')

    # período histórico
    now = datetime.utcnow()
    start = now - timedelta(days=period_days)

    # buscar leituras históricas do silo
    recent_cursor = readings_coll.find({'silo_id': siloId, 'timestamp': {'$gte': start, '$lte': now}}).sort('timestamp', -1)
    recent = []
    async for r in recent_cursor:
        recent.append(r)

    # calcular métricas para temperature, humidity e gas (co2)
    def compute_stats(values):
        vals = [v for v in values if v is not None]
        if not vals:
            return {'avg': None, 'p50': None, 'min': None, 'max': None, 'count': 0}
        try:
            return {'avg': float(mean(vals)), 'p50': float(median(vals)), 'min': float(min(vals)), 'max': float(max(vals)), 'count': len(vals)}
        except Exception:
            return {'avg': None, 'p50': None, 'min': None, 'max': None, 'count': len(vals)}

    temps = [r.get('temp_C') for r in recent if r.get('temp_C') is not None]
    hums = [r.get('rh_pct') for r in recent if r.get('rh_pct') is not None]
    co2s = [r.get('co2_ppm_est') for r in recent if r.get('co2_ppm_est') is not None]

    metrics = {
        'temperature': compute_stats(temps),
        'humidity': compute_stats(hums),
        'gas': compute_stats(co2s)
    }

    # buscar forecasts futuros para o silo no horizonte solicitado
    future_end = now + timedelta(days=period_days)
    fc_query = {'siloId': siloId, 'timestamp_forecast': {'$gte': now, '$lte': future_end}}
    f_cursor = fc.find(fc_query).sort('timestamp_forecast', 1)
    forecasts = []
    async for f in f_cursor:
        f['_id'] = str(f.get('_id'))
        forecasts.append(f)

    # gerar explicação textual
    weather = []
    w_cursor = meteorology_coll.find({'silo_id': siloId}).sort('fetched_at', -1).limit(20)
    async for w in w_cursor:
        weather.append(w)

    explanation = ml_service.generate_explanation_text(forecasts, recent, weather)

    return {'metrics': metrics, 'forecasts': forecasts, 'explanation': explanation}
