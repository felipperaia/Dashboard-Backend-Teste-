from fastapi import APIRouter, Depends, HTTPException
from .. import db, auth
from typing import List, Optional
from datetime import datetime, timedelta

router = APIRouter()


@router.get("/dashboard-summary")
async def dashboard_summary(limit: int = 5, user=Depends(auth.get_current_user)):
    """Retorna um resumo conciso do estado atual dos silos e métricas recentes."""
    # Últimos N leituras por silo (agrupar por silo)
    pipeline = [
        {"$sort": {"timestamp": -1}},
        {"$group": {"_id": "$silo_id", "latest": {"$first": "$ROOT"}}},
        {"$limit": limit}
    ]
    rows = await db.db.readings.aggregate(pipeline).to_list(limit)
    summaries = []
    for r in rows:
        lr = r.get("latest", {})
        summaries.append({
            "silo_id": lr.get("silo_id"),
            "timestamp": lr.get("timestamp"),
            "temp_C": lr.get("temp_C"),
            "rh_pct": lr.get("rh_pct"),
            "co2_ppm_est": lr.get("co2_ppm_est"),
            "mq2_raw": lr.get("mq2_raw"),
            "lux": lr.get("lux"),
            "luminosity_alert": lr.get("luminosity_alert"),
        })
    return {"summary_count": len(summaries), "summaries": summaries}


@router.get("/last-readings")
async def last_readings(silo_id: Optional[str] = None, limit: int = 20, user=Depends(auth.get_current_user)):
    q = {}
    if silo_id:
        q["silo_id"] = silo_id
    cursor = db.db.readings.find(q).sort("timestamp", -1).limit(limit)
    res = [r async for r in cursor]
    return res


@router.get("/alerts-summary")
async def alerts_summary(since_hours: int = 24, user=Depends(auth.get_current_user)):
    since = datetime.utcnow() - timedelta(hours=since_hours)
    cursor = db.db.alerts.find({"timestamp": {"$gte": since}}).sort("timestamp", -1).limit(200)
    alerts = [a async for a in cursor]
    counts = {}
    for a in alerts:
        counts[a.get("level", "unknown")] = counts.get(a.get("level", "unknown"), 0) + 1
    return {"since": since, "total": len(alerts), "by_level": counts, "alerts": alerts[:50]}
