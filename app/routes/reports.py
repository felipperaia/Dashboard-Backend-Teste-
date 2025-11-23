"""
routes/reports.py
CRUD de relatórios avançados (cria/lista/detalhes).
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional
from datetime import datetime
import numpy as np
from bson import ObjectId
from ..models import Report, ReportIn, ReportMetrics
from .. import auth
from ..db import get_collection
from ..template_utils.templates import render_tmpl
from fastapi.responses import StreamingResponse
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import io

router = APIRouter()


def oid(id: str) -> ObjectId:
    try:
        return ObjectId(id)
    except Exception:
        raise HTTPException(status_code=400, detail="id inválido")


def calc_metrics(values: List[float]) -> ReportMetrics:
    """Calcula métricas estatísticas de uma série de valores."""
    if not values:
        return ReportMetrics()
    arr = np.array(values)
    return ReportMetrics(
        min=float(np.min(arr)),
        max=float(np.max(arr)),
        avg=float(np.mean(arr)),
        count=len(arr),
        std_dev=float(np.std(arr)),
        p25=float(np.percentile(arr, 25)),
        p50=float(np.percentile(arr, 50)),  # mediana
        p75=float(np.percentile(arr, 75)),
    )


@router.post("/", response_model=Report)
async def create_report(body: ReportIn, user=Depends(auth.get_current_user)):
    # Busca nome do silo
    silos_coll = get_collection('silos')
    silo = await silos_coll.find_one({"_id": body.silo_id})
    if not silo:
        raise HTTPException(status_code=404, detail="Silo não encontrado")
    
    # Busca dados
    q = {"silo_id": body.silo_id, "timestamp": {"$gte": body.start, "$lte": body.end}}
    readings_coll = get_collection('readings')
    rows = [r async for r in readings_coll.find(q)]
    temps = [r.get("temperature") for r in rows if r.get("temperature") is not None]
    hums = [r.get("humidity") for r in rows if r.get("humidity") is not None]
    gases = [r.get("gas") for r in rows if r.get("gas") is not None]

    metrics = {
        "temperature": calc_metrics(temps).dict(),
        "humidity": calc_metrics(hums).dict(),
        "gas": calc_metrics(gases).dict(),
        "period": {"start": body.start, "end": body.end},
    }
    
    doc = {
        "silo_id": body.silo_id,
        "silo_name": silo.get("name", "Silo ?"),  # nome atual
        "start": body.start,
        "end": body.end,
        "title": body.title or f"Relatório {datetime.utcnow().date()}",
        "notes": body.notes or "",
        "metrics": metrics,
        "created_at": datetime.utcnow(),
        "created_by": user.get("_id"),
    }
    
    reports_coll = get_collection('reports')
    res = await reports_coll.insert_one(doc)
    created = await reports_coll.find_one({"_id": res.inserted_id})
    return created


@router.get("/", response_model=List[Report])
async def list_reports(silo_id: Optional[str] = None, limit: int = 100, user=Depends(auth.get_current_user)):
    q = {}
    if silo_id:
        q["silo_id"] = silo_id
    reports_coll = get_collection('reports')
    cur = reports_coll.find(q).sort("created_at", -1).limit(limit)
    return [r async for r in cur]


@router.get("/{report_id}", response_model=Report)
async def get_report(report_id: str, user=Depends(auth.get_current_user)):
    reports_coll = get_collection('reports')
    r = await reports_coll.find_one({"_id": oid(report_id)})
    if not r:
        raise HTTPException(status_code=404, detail="Relatório não encontrado")
    return r


@router.put("/{report_id}", response_model=Report)
async def update_report(report_id: str, body: ReportIn, user=Depends(auth.get_current_user)):
    reports_coll = get_collection('reports')
    old = await reports_coll.find_one({"_id": oid(report_id)})
    if not old:
        raise HTTPException(status_code=404, detail="Relatório não encontrado")
    await reports_coll.update_one({"_id": oid(report_id)}, {"$set": body.dict()})
    r = await reports_coll.find_one({"_id": oid(report_id)})
    return r


@router.delete("/{report_id}")
async def delete_report(report_id: str, user=Depends(auth.get_current_user)):
    reports_coll = get_collection('reports')
    old = await reports_coll.find_one({"_id": oid(report_id)})
    if not old:
        raise HTTPException(status_code=404, detail="Relatório não encontrado")
    # permitir delete apenas ao criador do relatório ou a admins
    if user.get('role') != 'admin' and str(old.get('created_by')) != str(user.get('_id')):
        raise HTTPException(status_code=403, detail='Apenas o criador ou admin pode deletar este relatório')
    await reports_coll.delete_one({"_id": oid(report_id)})
    return {"ok": True}


@router.get("/{report_id}/pdf")
async def report_pdf(report_id: str, user=Depends(auth.get_current_user)):
    r = await db.reports.find_one({"_id": oid(report_id)})
    if not r:
        raise HTTPException(status_code=404, detail="Relatório não encontrado")

    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    p.setFont("Helvetica-Bold", 16)
    p.drawString(40, 750, f"Relatório: {r.get('title', '')}")
    p.setFont("Helvetica", 10)
    p.drawString(40, 730, f"Silo: {r.get('silo_name', '')} ({r.get('silo_id')})")
    p.drawString(40, 715, f"Período: {r.get('start')} - {r.get('end')}")
    p.drawString(40, 700, f"Gerado em: {r.get('created_at')}")

    # inserir métricas simples
    y = 670
    metrics = r.get('metrics', {})
    for metric_name, metric_vals in metrics.items():
        if metric_name == 'period':
            continue
        p.setFont("Helvetica-Bold", 12)
        p.drawString(40, y, metric_name.capitalize())
        y -= 14
        p.setFont("Helvetica", 10)
        p.drawString(60, y, f"Min: {metric_vals.get('min')}")
        y -= 12
        p.drawString(60, y, f"Max: {metric_vals.get('max')}")
        y -= 12
        p.drawString(60, y, f"Avg: {metric_vals.get('avg')}")
        y -= 20

    p.showPage()
    p.save()
    buffer.seek(0)
    return StreamingResponse(buffer, media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename=report_{report_id}.pdf"})