"""
app.services.ml_service
Funções utilitárias para gerar explicações textuais a partir de previsões e dados.
"""
from typing import List, Dict, Any, Optional
from statistics import mean, median
from datetime import datetime, timedelta


def generate_explanation_text(forecasts: List[Dict[str, Any]], recent_readings: List[Dict[str, Any]], weather: List[Dict[str, Any]]) -> str:
    """Backward-compatible simple explanation (mantive a original como fallback).
    Mantém a função existente para casos simples e compatibilidade com outras rotas.
    """
    if not forecasts:
        return 'Sem previsões disponíveis.'

    # Agrupar por target
    by_target = {}
    for f in forecasts:
        t = f.get('target')
        by_target.setdefault(t, []).append(f)

    lines = []
    for target, items in by_target.items():
        values = [it.get('value_predicted') for it in items if it.get('value_predicted') is not None]
        if not values:
            continue
        avg = mean(values)
        trend = 'estável'
        try:
            if values[-1] > values[0] * 1.05:
                trend = 'subindo'
            elif values[-1] < values[0] * 0.95:
                trend = 'caindo'
        except Exception:
            pass
        lines.append(f'{target}: tendência {trend}, média prevista {avg:.2f}')

    # Simple risk indicator
    temp_vals = [v.get('value_predicted') for v in by_target.get('temperature', []) if v.get('value_predicted') is not None]
    hum_vals = [v.get('value_predicted') for v in by_target.get('humidity', []) if v.get('value_predicted') is not None]
    co2_vals = [v.get('value_predicted') for v in by_target.get('co2', []) if v.get('value_predicted') is not None]
    risk_lines = []
    try:
        if temp_vals and hum_vals and temp_vals[-1] > temp_vals[0] and hum_vals[-1] < hum_vals[0]:
            risk_lines.append('Condições de risco detectadas: temperatura subindo enquanto umidade cai.')
        if co2_vals and max(co2_vals) > 1000:
            risk_lines.append('Níveis de CO2 previstos acima de 1000 ppm — verificar ventilação.')
    except Exception:
        pass

    recs = []
    if risk_lines:
        recs.append('Recomendações: aumentar frequência de monitoramento; revisar ventilação; verificar dispositivos de exaustão.')

    out = '\n'.join(lines)
    if risk_lines:
        out += '\n' + '\n'.join(risk_lines)
    if recs:
        out += '\n' + '\n'.join(recs)
    return out


def generate_forecasts_from_readings(recent_readings: List[Dict[str, Any]], horizon_hours_list: Optional[List[int]] = None, targets: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """
    Gera previsões simples a partir de leituras históricas quando não há modelos Spark disponíveis.
    Estratégia: por alvo, calcula inclinação linear média (último - primeiro / horas) e extrapola para cada horizonte.
    Retorna lista de dicts com chaves: target, value_predicted, horizon_hours, timestamp_forecast
    """
    if horizon_hours_list is None:
        horizon_hours_list = [24, 48, 72, 168]
    if targets is None:
        targets = ['temperature', 'humidity', 'co2']

    # Map reading fields to canonical targets
    field_map = {
        'temperature': ['temp_C', 'temperature'],
        'humidity': ['rh_pct', 'humidity'],
        'co2': ['co2_ppm_est', 'co2']
    }

    out = []
    # Prepare series per target
    for target in targets:
        candidates = field_map.get(target, [target])
        series = []
        for r in recent_readings:
            for fld in candidates:
                if fld in r and r.get(fld) is not None:
                    try:
                        ts = r.get('timestamp')
                        if isinstance(ts, str):
                            ts = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                        elif isinstance(ts, (int, float)):
                            ts = datetime.utcfromtimestamp(ts)
                        raw = r.get(fld)
                        if raw is None:
                            continue
                        val = float(raw)
                        series.append((ts, val))
                    except Exception:
                        continue
                    break

        # sort by timestamp asc
        series.sort(key=lambda x: x[0])
        if not series:
            continue

        first_ts, first_val = series[0]
        last_ts, last_val = series[-1]
        hours_span = max(1.0, (last_ts - first_ts).total_seconds() / 3600.0)
        slope_per_hour = (last_val - first_val) / hours_span if hours_span else 0.0

        for h in horizon_hours_list:
            pred = last_val + slope_per_hour * h
            ts_forecast = last_ts + timedelta(hours=h)
            out.append({
                'target': target,
                'value_predicted': float(pred),
                'horizon_hours': int(h),
                'timestamp_forecast': ts_forecast.isoformat() + 'Z'
            })

    return out


def generate_soybean_storage_explanation(metrics: Dict[str, Any], forecasts: List[Dict[str, Any]], weather: List[Dict[str, Any]], period_days: int = 30) -> str:
    """
    Gera explicação textual específica para armazenamento de soja baseada em métricas e previsões.
    Regras heurísticas simples:
      - Temperatura média/prevista > 20C: risco moderado; >25C: risco alto
      - Umidade relativa média/prevista > 70%: risco alto (favor secagem/ventilação)
      - CO2 > 1000ppm: sinal de ventilação insuficiente
    Retorna texto com situação e recomendações práticas.
    """
    lines = []
    # Extract metrics
    try:
        temp_avg = metrics.get('temperature', {}).get('avg')
        temp_max = metrics.get('temperature', {}).get('max')
        hum_avg = metrics.get('humidity', {}).get('avg')
        hum_max = metrics.get('humidity', {}).get('max')
        gas_avg = metrics.get('gas', {}).get('avg')
    except Exception:
        temp_avg = temp_max = hum_avg = hum_max = gas_avg = None

    # Analyze forecasts by target for max predicted
    forecast_by_target = {}
    for f in forecasts:
        t = f.get('target')
        forecast_by_target.setdefault(t, []).append(f)

    def max_pred(target):
        vals = [x.get('value_predicted') for x in forecast_by_target.get(target, []) if x.get('value_predicted') is not None]
        return max(vals) if vals else None

    temp_fore_max = max_pred('temperature')
    hum_fore_max = max_pred('humidity')
    co2_fore_max = max_pred('co2')

    # Determine risk
    risk = 'estável'
    reasons = []
    if (temp_avg is not None and temp_avg > 25) or (temp_fore_max is not None and temp_fore_max > 25):
        risk = 'alto'
        reasons.append('temperatura muito alta (risco de aquecimento do grão)')
    elif (temp_avg is not None and temp_avg > 20) or (temp_fore_max is not None and temp_fore_max > 20):
        risk = 'moderado'
        reasons.append('temperatura elevada')

    if (hum_avg is not None and hum_avg > 75) or (hum_fore_max is not None and hum_fore_max > 75):
        # humidity critical
        risk = 'alto'
        reasons.append('umidade ambiente elevada (aumenta risco de fungos)')
    elif (hum_avg is not None and hum_avg > 65) or (hum_fore_max is not None and hum_fore_max > 65):
        if risk != 'alto':
            risk = 'moderado'
        reasons.append('umidade relativamente alta')

    if (co2_fore_max is not None and co2_fore_max > 1000) or (gas_avg is not None and gas_avg > 1000):
        if risk == 'estável':
            risk = 'moderado'
        reasons.append('aumento de CO2 — possível falta de ventilação')

    # Compose textual recommendation
    summary = f'Situação: risco {risk} para armazenagem de soja nos últimos {period_days} dias.'
    lines.append(summary)
    if reasons:
        lines.append('Motivos: ' + '; '.join(reasons) + '.')

    recs = []
    if risk == 'alto':
        recs.append('Ação imediata: verificar ventilação e iniciar inspeções internas a cada 6 horas.')
        recs.append('Se o grão estiver com alta umidade, considerar secagem urgente.')
    elif risk == 'moderado':
        recs.append('Aumentar frequência de monitoramento e ventilar por períodos curtos (2–4 horas).')
        recs.append('Rever histórico nas próximas 24 horas e preparar ações corretivas se tendência persistir.')
    else:
        recs.append('Condições estáveis: mantenha monitoramento regular e verifique sensores semanalmente.')

    # If forecasts show sharp increases, add a time-based suggestion
    try:
        if temp_fore_max and temp_fore_max - (temp_avg or 0) > 3:
            recs.append('Previsão indica aumento de temperatura próximo — agendar verificação em 12 horas.')
    except Exception:
        pass

    lines.append('Recomendações:')
    lines.extend(recs)
    return '\n'.join(lines)
