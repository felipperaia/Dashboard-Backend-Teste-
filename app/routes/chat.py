from fastapi import APIRouter, Depends, HTTPException, Query
from .. import config, db, auth
import httpx
from typing import List, Dict, Any, Optional
from . import rag as rag_routes

router = APIRouter()


class ChatMessage(Dict[str, str]):
    pass


@router.post("/")
async def chat(messages: List[ChatMessage], silo_id: Optional[str] = Query(None), include_recent: int = Query(0), user=Depends(auth.get_current_user)):
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
    if use_rag:
        # build RAG context using our internal endpoints
        try:
            summary = await rag_routes.dashboard_summary(limit=5, user=user)
            messages_out.append({"role": "system", "content": f"RAG_SUMMARY: {summary}"})
        except Exception as e:
            # fallback to direct DB reads
            pass

    # append user messages
    for m in messages:
        messages_out.append(m)

    payload = {"model": config.OPENROUTER_MODEL, "messages": messages_out, "temperature": 0.2}
    headers = {"Authorization": f"Bearer {config.OPENROUTER_API_KEY}"}
    async with httpx.AsyncClient(base_url="https://openrouter.ai/api/v1", timeout=60) as client:
        r = await client.post("/chat/completions", headers=headers, json=payload)
    if r.status_code >= 300:
        raise HTTPException(status_code=500, detail=f"OpenRouter erro: {r.text}")
    data = r.json()
    content = data.get("choices", [{}])[0].get("message", {}).get("content")
    return {"reply": content}
