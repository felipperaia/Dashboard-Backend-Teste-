# =========================
# Default templates e helpers
# =========================
from string import Template
from typing import Dict, Any

DEFAULT_TEMPLATES = {
    "email_subject": "Alerta no Silo ${silo_name} em ${timestamp}",
    "email_body": (
        "Silo: ${silo_name}\n"
        "Data/Hora: ${timestamp}\n"
        "Temperatura: ${temperature}\n"
        "Umidade: ${humidity}\n"
        "Gás: ${gas}\n"
        "Limites: T=${max_temp} U=${max_humidity} G=${max_gas}\n"
        "Ocorrências: ${violations}"
    ),
    "sms_body": "ALERTA ${silo_name}: T=${temperature} U=${humidity} G=${gas} em ${timestamp}",
    "telegram_text": "🚨 Alerta no Silo ${silo_name}\nT=${temperature} U=${humidity} G=${gas}\n${violations}\n${timestamp}",
    "telegram_parse_mode": None,
    "popup_text": "Alerta no Silo ${silo_name}: ${violations}",
}


def merge_templates(silo_templates: Dict[str, Any]) -> Dict[str, Any]:
    """Mescla templates defaults com customizados do silo."""
    merged = DEFAULT_TEMPLATES.copy()
    if silo_templates:
        for k, v in silo_templates.items():
            if v is not None:
                merged[k] = v
    return merged


def render_tmpl(tmpl: str, ctx: Dict[str, Any]) -> str:
    """Renderiza template com contexto fornecido."""
    if not tmpl:
        return ""
    return Template(tmpl).safe_substitute(ctx)