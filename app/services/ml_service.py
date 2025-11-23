"""
app.services.ml_service
Funções utilitárias para gerar explicações textuais a partir de previsões e dados.
"""
from typing import List, Dict, Any
from statistics import mean

def generate_explanation_text(forecasts: List[Dict[str, Any]], recent_readings: List[Dict[str, Any]], weather: List[Dict[str, Any]]) -> str:
    """Gera um resumo simples a partir das previsões.
    Entrada:
      - forecasts: lista de documentos de forecast (cada item com 'target', 'timestamp_forecast', 'value_predicted', 'horizon_hours')
      - recent_readings: leituras recentes do silo
      - weather: dados meteorológicos salvos
    Retorna string curta com tendências e recomendações.
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
        if values[-1] > values[0] * 1.05:
            trend = 'subindo'
        elif values[-1] < values[0] * 0.95:
            trend = 'caindo'
        lines.append(f'{target}: tendência {trend}, média prevista {avg:.2f}')

    # Simple risk indicator: if temperature rising AND humidity falling AND co2 high
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
