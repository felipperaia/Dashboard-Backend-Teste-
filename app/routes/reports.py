"""
routes/reports.py

CRUD de relatórios avançados (cria/lista/detalhes + PDF).
"""

from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional
from datetime import datetime
import numpy as np
from bson import ObjectId

from ..models import Report, ReportIn, ReportMetrics
from .. import auth
from ..db import get_collection
from fastapi.responses import StreamingResponse

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

import io
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

router = APIRouter()


def oid(id_str: str) -> ObjectId:
    """Converte string para ObjectId, com tratamento de erro."""
    try:
        return ObjectId(id_str)
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
        stddev=float(np.std(arr)),
        p25=float(np.percentile(arr, 25)),
        p50=float(np.percentile(arr, 50)),  # mediana
        p75=float(np.percentile(arr, 75)),
    )


@router.post("/", response_model=Report)
async def create_report(body: ReportIn, user=Depends(auth.get_current_user)):
    """
    Cria um novo relatório:
    - Busca o silo pelo id
    - Coleta leituras no período
    - Calcula métricas (min, max, média, mediana etc.)
    - Agrega métricas de previsões (forecast_demeter)
    - Salva documento em 'reports'
    """
    silos_coll = get_collection("silos")

    # body.silo_id vem como string → converter para ObjectId para buscar o silo
    silo = await silos_coll.find_one({"_id": oid(body.silo_id)})
    if not silo:
        raise HTTPException(status_code=404, detail="Silo não encontrado")

    # ---------------- Leituras do período ----------------
    readings_coll = get_collection("readings")

    q = {
        "silo_id": body.silo_id,  # nas leituras você grava silo_id como string
        "timestamp": {"$gte": body.start, "$lte": body.end},
    }
    rows = [r async for r in readings_coll.find(q)]

    # Suportar tanto campos normalizados (temperature/humidity/gas)
    # quanto os crus (temp_C/rh_pct/mq2_raw) se for o caso.
    temps = []
    hums = []
    gases = []

    for r in rows:
        # temperatura
        if r.get("temperature") is not None:
            temps.append(r.get("temperature"))
        elif r.get("temp_C") is not None:
            temps.append(r.get("temp_C"))

        # umidade
        if r.get("humidity") is not None:
            hums.append(r.get("humidity"))
        elif r.get("rh_pct") is not None:
            hums.append(r.get("rh_pct"))

        # gases (ex.: MQ2)
        if r.get("gas") is not None:
            gases.append(r.get("gas"))
        elif r.get("mq2_raw") is not None:
            gases.append(r.get("mq2_raw"))

    metrics = {
        "temperature": calc_metrics(temps).dict(),
        "humidity": calc_metrics(hums).dict(),
        "gas": calc_metrics(gases).dict(),
        "period": {"start": body.start, "end": body.end},
    }

    # ---------------- Métricas de previsões (Spark) ----------------
    try:
        forecast_coll = get_collection("forecast_demeter")

        # Spark grava como 'siloId'; ainda assim suportamos 'silo_id' se existir
        fq = {
            "timestamp_forecast": {"$gte": body.start, "$lte": body.end},
            "$or": [
                {"siloId": body.silo_id},
                {"silo_id": body.silo_id},
            ],
        }
        frows = [f async for f in forecast_coll.find(fq)]
    except Exception:
        frows = []

    spark_metrics = {}
    if frows:
        by_target = {}
        for fr in frows:
            tgt = fr.get("target") or "unknown"
            by_target.setdefault(tgt, []).append(fr)

        for tgt, items in by_target.items():
            vals = [
                it.get("value_predicted")
                for it in items
                if it.get("value_predicted") is not None
            ]
            spark_metrics[tgt] = {
                "count": len(items),
                "min": min(vals) if vals else None,
                "max": max(vals) if vals else None,
                "avg": (sum(vals) / len(vals)) if vals else None,
            }

    # ---------------- Montar doc do relatório ----------------
    doc = {
        "silo_id": body.silo_id,
        "silo_name": silo.get("name", "Silo ?"),
        "start": body.start,
        "end": body.end,
        "title": body.title or f"Relatório {datetime.utcnow().date()}",
        "notes": body.notes or "",
        "metrics": metrics,
        "spark_metrics": spark_metrics,
        "created_at": datetime.utcnow(),
        "created_by": user.get("_id"),
    }

    reports_coll = get_collection("reports")
    res = await reports_coll.insert_one(doc)
    created = await reports_coll.find_one({"_id": res.inserted_id})

    if created:
        created["_id"] = str(created["_id"])

    return created


@router.get("/", response_model=List[Report])
async def list_reports(
    silo_id: Optional[str] = None,
    limit: int = 100,
    user=Depends(auth.get_current_user),
):
    """Lista relatórios, opcionalmente filtrando por silo_id."""
    q = {}
    if silo_id:
        q["silo_id"] = silo_id

    reports_coll = get_collection("reports")
    cur = reports_coll.find(q).sort("created_at", -1).limit(limit)
    out = []
    async for r in cur:
        if r.get("_id"):
            r["_id"] = str(r["_id"])
        out.append(r)
    return out


@router.get("/{report_id}", response_model=Report)
async def get_report(report_id: str, user=Depends(auth.get_current_user)):
    """Retorna um relatório específico por ID."""
    reports_coll = get_collection("reports")
    r = await reports_coll.find_one({"_id": oid(report_id)})
    if not r:
        raise HTTPException(status_code=404, detail="Relatório não encontrado")
    r["_id"] = str(r["_id"])
    return r


@router.put("/{report_id}", response_model=Report)
async def update_report(
    report_id: str, body: ReportIn, user=Depends(auth.get_current_user)
):
    """Atualiza os campos básicos de um relatório."""
    reports_coll = get_collection("reports")
    old = await reports_coll.find_one({"_id": oid(report_id)})
    if not old:
        raise HTTPException(status_code=404, detail="Relatório não encontrado")

    await reports_coll.update_one({"_id": oid(report_id)}, {"$set": body.dict()})
    r = await reports_coll.find_one({"_id": oid(report_id)})
    if r.get("_id"):
        r["_id"] = str(r["_id"])
    return r


@router.delete("/{report_id}")
async def delete_report(report_id: str, user=Depends(auth.get_current_user)):
    """Deleta um relatório (apenas criador ou admin)."""
    reports_coll = get_collection("reports")
    old = await reports_coll.find_one({"_id": oid(report_id)})
    if not old:
        raise HTTPException(status_code=404, detail="Relatório não encontrado")

    # permitir delete apenas ao criador do relatório ou a admins
    if user.get("role") != "admin" and str(old.get("created_by")) != str(
        user.get("_id")
    ):
        raise HTTPException(
            status_code=403,
            detail="Apenas o criador ou admin pode deletar este relatório",
        )

    await reports_coll.delete_one({"_id": oid(report_id)})
    return {"ok": True}


@router.get("/{report_id}/pdf")
async def report_pdf(report_id: str, user=Depends(auth.get_current_user)):
    """
    Gera PDF do relatório com:
    - Título, meta (silo, período, criado em)
    - Gráfico de série temporal (temperatura + umidade)
    - Métricas calculadas
    - Métricas de previsão Spark
    - Meteorologia 7 dias (se disponível)
    """
    reports_coll = get_collection("reports")
    r = await reports_coll.find_one({"_id": oid(report_id)})
    if not r:
        raise HTTPException(status_code=404, detail="Relatório não encontrado")

    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)

    # Cabeçalho
    p.setFont("Helvetica-Bold", 16)
    p.drawString(40, 750, f"Relatório: {r.get('title', '')}")
    p.setFont("Helvetica", 10)
    p.drawString(40, 730, f"Silo: {r.get('silo_name', '')} ({r.get('silo_id')})")
    p.drawString(40, 715, f"Período: {r.get('start')} - {r.get('end')}")
    p.drawString(40, 700, f"Gerado em: {r.get('created_at')}")

    # -------- Gráfico de série temporal --------
    readings_coll = get_collection("readings")
    try:
        q = {
            "silo_id": r.get("silo_id"),
            "timestamp": {"$gte": r.get("start"), "$lte": r.get("end")},
        }
        rows = [row async for row in readings_coll.find(q).sort("timestamp", 1)]
    except Exception:
        rows = []

    if rows:
        df = pd.DataFrame(rows)
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"])

        temp_col = (
            "temperature"
            if "temperature" in df.columns
            else ("temp_C" if "temp_C" in df.columns else None)
        )
        hum_col = (
            "humidity"
            if "humidity" in df.columns
            else ("rh_pct" if "rh_pct" in df.columns else None)
        )

        plt.figure(figsize=(6, 2.5))
        if temp_col:
            plt.plot(
                df["timestamp"],
                df[temp_col],
                label="Temperatura (°C)",
                color="#ef4444",
            )
        if hum_col:
            plt.plot(
                df["timestamp"],
                df[hum_col],
                label="Umidade (%)",
                color="#3b82f6",
            )
        plt.legend(loc="upper right")
        plt.tight_layout()

        imgbuf = io.BytesIO()
        plt.savefig(imgbuf, format="png", dpi=150)
        plt.close()
        imgbuf.seek(0)
        img = ImageReader(imgbuf)

        p.drawImage(img, 40, 420, width=520, height=220)

    # -------- Resumo de métricas --------
    y = 400
    metrics = r.get("metrics", {})

    for metric_name, metric_vals in metrics.items():
        if metric_name == "period":
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
        y -= 12
        p.drawString(60, y, f"Mediana: {metric_vals.get('p50')}")
        y -= 20

    # -------- Métricas de previsão (Spark) --------
    spark_metrics = r.get("spark_metrics") or {}
    if spark_metrics:
        p.setFont("Helvetica-Bold", 12)
        p.drawString(40, y, "Métricas de Previsão (Spark)")
        y -= 16
        p.setFont("Helvetica", 10)
        for tgt, vals in spark_metrics.items():
            p.drawString(
                40,
                y,
                f"{tgt}: count={vals.get('count')}, min={vals.get('min')}, "
                f"max={vals.get('max')}, avg={vals.get('avg')}",
            )
            y -= 12
        y -= 8

    # -------- Meteorologia 7 dias (se disponível) --------
    met_coll = get_collection("meteorology")
    met_doc = await met_coll.find_one(
        {"silo_id": r.get("silo_id")}, sort=[("fetched_at", -1)]
    )

    if met_doc and met_doc.get("data"):
        daily = met_doc["data"].get("daily", {})
        times = daily.get("time", [])
        tmax = daily.get("temperature_2m_max", [])
        tmin = daily.get("temperature_2m_min", [])
        precip = daily.get("precipitation_sum", [])

        p.setFont("Helvetica-Bold", 12)
        p.drawString(40, y, "Previsão (7 dias)")
        y -= 16

        p.setFont("Helvetica", 9)
        max_cols = min(7, len(times))
        for i in range(max_cols):
            tx = times[i]
            date_str = str(tx)
            p.drawString(
                40,
                y,
                f"{date_str}: "
                f"T_max={tmax[i] if i < len(tmax) else 'n/a'} "
                f"T_min={tmin[i] if i < len(tmin) else 'n/a'} "
                f"P={precip[i] if i < len(precip) else 'n/a'}",
            )
            y -= 12

    p.showPage()
    p.save()
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=report_{report_id}.pdf"},
    )
