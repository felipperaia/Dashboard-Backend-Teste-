from fastapi import APIRouter, Depends, HTTPException, Query
from .. import config, db, auth
import httpx
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from . import rag as rag_routes
from . import reports as reports_routes
from fastapi.responses import StreamingResponse

router = APIRouter()


class ChatMessage(Dict[str, str]):
    pass


@router.post("/")
async def chat(messages: List[ChatMessage], silo_id: Optional[str] = Query(None), include_recent: int = Query(0), stream: bool = Query(False), user=Depends(auth.get_current_user)):
    """Encaminha conversa para OpenRouter. Se `silo_id` for fornecido, anexa leituras recentes como contexto.
    Variáveis de ambiente: OPENROUTER_API_KEY, OPENROUTER_MODEL, LLM_SYSTEM_PROMPT
    """
    if not config.OPENROUTER_API_KEY:
        raise HTTPException(status_code=400, detail="OPENROUTER_API_KEY não configurada")

    messages_out = []
    # system prompt
    if config.LLM_SYSTEM_PROMPT:
        messages_out.append({"role": "system", "content": config.LLM_SYSTEM_PROMPT})

    # optional context from DB or RAG endpoints
    if silo_id and include_recent > 0:
        cursor = db.db.readings.find({"silo_id": silo_id}).sort("timestamp", -1).limit(include_recent)
        recent = []
        async for r in cursor:
            recent.append({"timestamp": str(r.get("timestamp")), "temp": r.get("temp_C") or r.get("temperature"), "rh": r.get("rh_pct") or r.get("humidity")})
        messages_out.append({"role": "system", "content": f"Contexto: últimas {len(recent)} leituras do silo {silo_id}: {recent}"})
    # Use RAG context if enabled in config
    use_rag = getattr(config, 'USE_RAG', True)
    if use_rag:
        rag_parts = []
        # 1) dashboard summary
        try:
            summary = await rag_routes.dashboard_summary(limit=6, user=user)
            rag_parts.append(f"DASHBOARD_SUMMARY: {json.dumps(summary, default=str)}")
        except Exception as e:
            rag_parts.append(f"DASHBOARD_SUMMARY: error fetching summary: {e}")

        # 2) alerts summary (last 24h)
        try:
            alerts = await rag_routes.alerts_summary(since_hours=24, user=user)
            rag_parts.append(f"ALERTS_SUMMARY: {json.dumps(alerts, default=str)}")
        except Exception as e:
            rag_parts.append(f"ALERTS_SUMMARY: error fetching alerts: {e}")

        # 3) recent readings for the silo (if provided)
        if silo_id:
            try:
                recent_readings = await rag_routes.last_readings(silo_id=silo_id, limit=include_recent or 20, user=user)
                rag_parts.append(f"RECENT_READINGS_SILO_{silo_id}: {json.dumps(recent_readings, default=str)}")
            except Exception as e:
                rag_parts.append(f"RECENT_READINGS_SILO_{silo_id}: error: {e}")

        # 4) reports: list and include metrics of recent reports (limit 10)
        try:
            reports_list = await reports_routes.list_reports(limit=10, user=user)
            # include high-level info about each report and metrics
            short_reports = []
            for rp in reports_list:
                try:
                    rid = str(rp.get('_id'))
                    full = await reports_routes.get_report(rid, user=user)
                    short_reports.append({
                        'id': rid,
                        'title': full.get('title'),
                        'silo_name': full.get('silo_name'),
                        'start': str(full.get('start')),
                        'end': str(full.get('end')),
                        'metrics': full.get('metrics')
                    })
                except Exception:
                    short_reports.append({'id': str(rp.get('_id')), 'title': rp.get('title')})
            rag_parts.append(f"REPORTS: {json.dumps(short_reports, default=str)}")
        except Exception as e:
            rag_parts.append(f"REPORTS: error fetching reports: {e}")

        # 5) Add README.md (project documentation) to give system-level knowledge
        try:
            repo_root = Path(__file__).resolve().parents[2]
            readme_path = repo_root / 'README.md'
            if readme_path.exists():
                readme_text = readme_path.read_text(encoding='utf-8')[:8000]
                rag_parts.append(f"SYSTEM_README: {readme_text}")
            else:
                rag_parts.append("SYSTEM_README: README.md not found in repository root")
        except Exception as e:
            rag_parts.append(f"SYSTEM_README: error reading README: {e}")

        # Compose single system message with strict scope instruction
        scope_instruction = (
            "RAG_CONTEXT_START\n"
            "Este contexto contém exclusivamente informações do sistema Deméter (backend, rotas, relatórios, leituras, alertas, documentação). "
            "RESPONDA APENAS SOBRE ESTES DADOS E SOBRE COMO O SISTEMA FUNCIONA. NÃO FORNEÇA INFORMAÇÕES EXTERNAS OU NÃO RELACIONADAS AO SISTEMA. "
            "Se o usuário pedir conselhos fora do escopo (ex.: ferraria, horticultura que não seja sobre armazenamento/monitoramento de grãos), recuse e indique que não é coberto.\n"
        )
        rag_payload = scope_instruction + "\n\n" + "\n\n".join(rag_parts)
        messages_out.append({"role": "system", "content": rag_payload})

    # append user messages
    for m in messages:
        messages_out.append(m)

    # Try main model and fallbacks if configured
    models_to_try = [config.OPENROUTER_MODEL] + [m for m in getattr(config, 'FALLBACK_OPENROUTER_MODELS', []) if m != config.OPENROUTER_MODEL]
    headers = {"Authorization": f"Bearer {config.OPENROUTER_API_KEY}"}

    # Add streaming flag to payload when requested
    base_payload = {"messages": messages_out, "temperature": 0.2}
    if stream:
        base_payload['stream'] = True

    async with httpx.AsyncClient(base_url="https://openrouter.ai/api/v1", timeout=300) as client:
        last_err = None
        for model in models_to_try:
            payload = dict(base_payload)
            payload['model'] = model
            try:
                if stream:
                    # stream response back to client
                    resp = await client.stream("POST", "/chat/completions", headers=headers, json=payload)
                    if resp.status_code >= 300:
                        last_err = await resp.aread()
                        continue

                    async def event_stream():
                        try:
                            async for chunk in resp.aiter_bytes():
                                if not chunk:
                                    continue
                                yield chunk
                        finally:
                            await resp.aclose()

                    return StreamingResponse(event_stream(), media_type="text/event-stream")

                else:
                    r = await client.post("/chat/completions", headers=headers, json=payload)
                    if r.status_code >= 300:
                        last_err = await r.aread()
                        continue
                    data = r.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content")
                    return {"reply": content, "model_used": model}
            except Exception as e:
                last_err = e
                continue

    # If we reach here, all models failed
    raise HTTPException(status_code=500, detail=f"OpenRouter erro: {last_err}")
