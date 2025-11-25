"""
routes/reports.py (versão corrigida)
CRUD de relatórios avançados.

MUDANÇAS:
1. Função report_pdf() agora:
   - Busca relatório corretamente por silo_id
   - Gera modelo de fala (explicação em português simples)
   - Inclui todas as métricas: mediana, média, min, max, previsões
   - Draw correto no PDF com formatação profissional

2. Função create_report() agora:
   - Normaliza silo_id (ObjectId -> str)
   - Calcula spark_metrics corretamente
"""

from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional
from datetime import datetime
import numpy as np
from bson import ObjectId
from ..models import Report, ReportIn, ReportMetrics
from .. import auth
from ..db import get_collection
from ..services.ml_service import generate_explanation_text
from fastapi.responses import StreamingResponse
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.lib.units import inch
import io
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

router = APIRouter()


def oid(id_str):
    """Converte string para ObjectId."""
    try:
        return ObjectId(id_str)
    except:
        raise HTTPException(status_code=400, detail="ID inválido")


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
        p50=float(np.percentile(arr, 50)),  # Mediana
        p75=float(np.percentile(arr, 75)),
    )


@router.post("/", response_model=Report)
async def create_report(body: ReportIn, user=Depends(auth.get_current_user)):
    """Cria novo relatório: busca dados, calcula métricas, salva no MongoDB."""
    
    silos_coll = get_collection("silos")
    silo = await silos_coll.find_one({"_id": oid(body.silo_id)})
    if not silo:
        raise HTTPException(status_code=404, detail="Silo não encontrado")

    silo_name = silo.get("name", "Silo ?")

    # ============ Buscar readings no período ==============
    q = {
        "silo_id": str(silo.get("_id")),
        "timestamp": {"$gte": body.start, "$lte": body.end},
    }
    readings_coll = get_collection("readings")
    rows = []
    async for r in readings_coll.find(q):
        rows.append(r)

    # ============ Calcular métricas de sensores ==============
    temps = [r.get("temperature") for r in rows if r.get("temperature") is not None]
    hums = [r.get("humidity") for r in rows if r.get("humidity") is not None]
    gases = [r.get("gas") for r in rows if r.get("gas") is not None]

    metrics = {
        "temperature": calc_metrics(temps).dict(),
        "humidity": calc_metrics(hums).dict(),
        "gas": calc_metrics(gases).dict(),
        "period": {"start": body.start, "end": body.end},
    }

    # ============ Buscar previsões Sparkz ==============
    spark_metrics = {}
    try:
        forecast_coll = get_collection("forecast_demeter")
        fq = {
            "siloId": str(silo.get("_id")),
            "timestamp_forecast": {"$gte": body.start, "$lte": body.end},
        }
        frows = []
        async for f in forecast_coll.find(fq):
            frows.append(f)

        # Agrupar por target e calcular estatísticas
        by_target = {}
        for fr in frows:
            tgt = fr.get("target", "unknown")
            by_target.setdefault(tgt, []).append(fr)

        for tgt, items in by_target.items():
            vals = [it.get("value_predicted") for it in items if it.get("value_predicted") is not None]
            spark_metrics[tgt] = {
                "count": len(items),
                "min": min(vals) if vals else None,
                "max": max(vals) if vals else None,
                "avg": sum(vals) / len(vals) if vals else None,
                "median": float(np.median(vals)) if vals else None,
            }

    except Exception as e:
        print(f"Warning: could not fetch spark metrics: {e}")

    # ============ Salvar documento ==============
    doc = {
        "silo_id": str(silo.get("_id")),
        "silo_name": silo_name,
        "start": body.start,
        "end": body.end,
        "title": body.title or f"Relatório {datetime.utcnow().date()}",
        "notes": body.notes or "",
        "metrics": metrics,
        "spark_metrics": spark_metrics,
        "created_at": datetime.utcnow(),
        "created_by": user.get("id"),
    }

    reports_coll = get_collection("reports")
    res = await reports_coll.insert_one(doc)
    created = await reports_coll.find_one({"_id": res.inserted_id})

    if created:
        created["id"] = str(created["_id"])

    return created


@router.get("/", response_model=List[Report])
async def list_reports(
    silo_id: Optional[str] = None, limit: int = 100, user=Depends(auth.get_current_user)
):
    """Lista relatórios do usuário (opcionalmente filtrado por silo)."""
    q = {}
    if silo_id:
        q["silo_id"] = silo_id

    reports_coll = get_collection("reports")
    cur = reports_coll.find(q).sort("created_at", -1).limit(limit)
    out = []
    async for r in cur:
        r["id"] = str(r["_id"])
        out.append(r)
    return out


@router.get("/{report_id}", response_model=Report)
async def get_report(report_id: str, user=Depends(auth.get_current_user)):
    """Busca relatório por ID."""
    reports_coll = get_collection("reports")
    r = await reports_coll.find_one({"_id": oid(report_id)})
    if not r:
        raise HTTPException(status_code=404, detail="Relatório não encontrado")
    r["id"] = str(r["_id"])
    return r


@router.put("/{report_id}", response_model=Report)
async def update_report(
    report_id: str, body: ReportIn, user=Depends(auth.get_current_user)
):
    """Atualiza relatório."""
    reports_coll = get_collection("reports")
    old = await reports_coll.find_one({"_id": oid(report_id)})
    if not old:
        raise HTTPException(status_code=404, detail="Relatório não encontrado")

    await reports_coll.update_one({"_id": oid(report_id)}, {"$set": body.dict()})
    r = await reports_coll.find_one({"_id": oid(report_id)})
    r["id"] = str(r["_id"])
    return r


@router.delete("/{report_id}")
async def delete_report(report_id: str, user=Depends(auth.get_current_user)):
    """Deleta relatório (apenas criador ou admin)."""
    reports_coll = get_collection("reports")
    old = await reports_coll.find_one({"_id": oid(report_id)})
    if not old:
        raise HTTPException(status_code=404, detail="Relatório não encontrado")

    if user.get("role") != "admin" and str(old.get("created_by")) != str(user.get("id")):
        raise HTTPException(
            status_code=403,
            detail="Apenas o criador ou admin pode deletar este relatório",
        )

    await reports_coll.delete_one({"_id": oid(report_id)})
    return {"ok": True}


def generate_report_explanation(metrics: dict, spark_metrics: dict, silo_name: str) -> str:
    """
    Gera um texto em português simples explicando o relatório.
    Modelo de fala profissional mas acessível.
    """
    lines = []
    lines.append(f"=== RELATÓRIO DO SILO: {silo_name} ===\n")

    # ============ Temperatura ==============
    temp_metrics = metrics.get("temperature", {})
    if temp_metrics.get("count", 0) > 0:
        lines.append("📊 TEMPERATURA:")
        lines.append(f"  • Média: {temp_metrics.get('avg', 0):.1f}°C")
        lines.append(f"  • Mediana (valor central): {temp_metrics.get('p50', 0):.1f}°C")
        lines.append(f"  • Mínima: {temp_metrics.get('min', 0):.1f}°C")
        lines.append(f"  • Máxima: {temp_metrics.get('max', 0):.1f}°C")
        lines.append(f"  • Leituras coletadas: {temp_metrics.get('count', 0)}\n")

    # ============ Umidade ==============
    hum_metrics = metrics.get("humidity", {})
    if hum_metrics.get("count", 0) > 0:
        lines.append("💧 UMIDADE RELATIVA:")
        lines.append(f"  • Média: {hum_metrics.get('avg', 0):.1f}%")
        lines.append(f"  • Mediana (valor central): {hum_metrics.get('p50', 0):.1f}%")
        lines.append(f"  • Mínima: {hum_metrics.get('min', 0):.1f}%")
        lines.append(f"  • Máxima: {hum_metrics.get('max', 0):.1f}%\n")

    # ============ Gases ==============
    gas_metrics = metrics.get("gas", {})
    if gas_metrics.get("count", 0) > 0:
        lines.append("⚠️ GASES DETECTADOS:")
        lines.append(f"  • Média: {gas_metrics.get('avg', 0):.1f} ppm")
        lines.append(f"  • Mediana (valor central): {gas_metrics.get('p50', 0):.1f} ppm")
        lines.append(f"  • Máxima detectada: {gas_metrics.get('max', 0):.1f} ppm\n")

    # ============ Previsões Sparkz ==============
    if spark_metrics:
        lines.append("🔮 PREVISÕES GERADAS (Machine Learning):")
        for target, stats in spark_metrics.items():
            if stats.get("count", 0) > 0:
                lines.append(f"  📌 {target.upper()}:")
                lines.append(f"     - Previsões geradas: {stats.get('count')}")
                lines.append(f"     - Valor médio previsto: {stats.get('avg', 0):.2f}")
                lines.append(f"     - Mediana das previsões: {stats.get('median', 0):.2f}")
                lines.append(f"     - Intervalo: {stats.get('min', 0):.2f} a {stats.get('max', 0):.2f}\n")

    # ============ Recomendações ==============
    lines.append("✅ ANÁLISE E RECOMENDAÇÕES:")
    if temp_metrics.get("avg", 0) > 30:
        lines.append("  • Temperatura elevada detectada. Verificar ventilação ou refrigeração.")
    if hum_metrics.get("avg", 0) < 30:
        lines.append("  • Umidade baixa. Pode afetar armazenamento. Considerar umidificação.")
    if hum_metrics.get("avg", 0) > 80:
        lines.append("  • Umidade muito alta. Risco de mofo/condensação. Melhorar ventilação.")
    if gas_metrics.get("max", 0) > 1000:
        lines.append("  • Níveis de gases acima do esperado. Verificar hermeticidade.")

    return "\n".join(lines)


@router.get("/{report_id}/pdf")
async def report_pdf(report_id: str, user=Depends(auth.get_current_user)):
    """
    Gera PDF do relatório com:
    - Título, metadados (silo, período, criado em)
    - Gráfico de série temporal (temperatura, umidade)
    - Tabela com métricas estatísticas
    - Previsões Sparkz (mediana, média, min, max)
    - Texto explicativo (modelo de fala em português)
    - Meteorologia 7 dias (se disponível)
    """
    reports_coll = get_collection("reports")
    r = await reports_coll.find_one({"_id": oid(report_id)})
    if not r:
        raise HTTPException(status_code=404, detail="Relatório não encontrado")

    # ============ Preparar buffer PDF ==============
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    page_width, page_height = letter
    margin_left = 40
    margin_top = 750
    y = margin_top

    # ============ CABEÇALHO ==============
    p.setFont("Helvetica-Bold", 16)
    p.drawString(margin_left, y, f"RELATÓRIO: {r.get('title', 'Sem título')}")
    y -= 20

    p.setFont("Helvetica", 10)
    p.drawString(margin_left, y, f"Silo: {r.get('silo_name', 'N/A')} | ID: {r.get('silo_id', 'N/A')}")
    y -= 14
    start_date = r.get("start").strftime("%d/%m/%Y") if hasattr(r.get("start"), "strftime") else str(r.get("start"))
    end_date = r.get("end").strftime("%d/%m/%Y") if hasattr(r.get("end"), "strftime") else str(r.get("end"))
    p.drawString(margin_left, y, f"Período: {start_date} a {end_date}")
    y -= 14
    created_at = r.get("created_at").strftime("%d/%m/%Y %H:%M:%S") if hasattr(r.get("created_at"), "strftime") else str(r.get("created_at"))
    p.drawString(margin_left, y, f"Gerado em: {created_at}")
    y -= 20

    # ============ GRÁFICO DE SÉRIE TEMPORAL ==============
    try:
        readings_coll = get_collection("readings")
        q = {
            "silo_id": r.get("silo_id"),
            "timestamp": {"$gte": r.get("start"), "$lte": r.get("end")},
        }
        rows = []
        async for row in readings_coll.find(q).sort("timestamp", 1):
            rows.append(row)

        if rows:
            df = pd.DataFrame(rows)
            if "timestamp" in df.columns:
                df["timestamp"] = pd.to_datetime(df["timestamp"])

            # Plotar temperatura e umidade
            plt.figure(figsize=(6, 2.5))
            if "temperature" in df.columns:
                plt.plot(df["timestamp"], df["temperature"], label="Temperatura (°C)", color="#ef4444")
            if "humidity" in df.columns:
                plt.plot(df["timestamp"], df["humidity"], label="Umidade (%)", color="#3b82f6")
            plt.legend(loc="upper right", fontsize=8)
            plt.tight_layout()

            img_buf = io.BytesIO()
            plt.savefig(img_buf, format="png", dpi=150)
            plt.close()
            img_buf.seek(0)
            img = ImageReader(img_buf)

            p.drawString(margin_left, y, "SÉRIE TEMPORAL - ÚLTIMOS 7 DIAS")
            y -= 14
            p.drawImage(img, margin_left, y - 180, width=500, height=180)
            y -= 200

    except Exception as e:
        print(f"Warning: could not create time series graph: {e}")
        y -= 20

    # ============ MÉTRICAS ESTATÍSTICAS ==============
    p.setFont("Helvetica-Bold", 12)
    p.drawString(margin_left, y, "MÉTRICAS ESTATÍSTICAS")
    y -= 16

    metrics = r.get("metrics", {})
    for metric_name, metric_vals in metrics.items():
        if metric_name == "period":
            continue  # Pular campo de período

        p.setFont("Helvetica-Bold", 11)
        p.drawString(margin_left, y, f"{metric_name.upper()}")
        y -= 12

        p.setFont("Helvetica", 9)
        metric_labels = [
            ("Min", "min"),
            ("Max", "max"),
            ("Média", "avg"),
            ("Mediana", "p50"),
            ("Desvio Padrão", "stddev"),
            ("P25", "p25"),
            ("P75", "p75"),
            ("Contagem", "count"),
        ]
        for label, key in metric_labels:
            val = metric_vals.get(key)
            if val is not None:
                p.drawString(margin_left + 20, y, f"  • {label}: {val:.2f}" if isinstance(val, (int, float)) else f"  • {label}: {val}")
                y -= 10

        y -= 6

    # ============ PREVISÕES SPARKZ ==============
    spark_metrics = r.get("spark_metrics", {})
    if spark_metrics:
        p.setFont("Helvetica-Bold", 12)
        p.drawString(margin_left, y, "PREVISÕES (MACHINE LEARNING)")
        y -= 16

        p.setFont("Helvetica", 9)
        for target, vals in spark_metrics.items():
            p.setFont("Helvetica-Bold", 10)
            p.drawString(margin_left, y, f"{target.upper()}")
            y -= 11

            p.setFont("Helvetica", 9)
            forecast_labels = [
                ("Contagem", "count"),
                ("Mínimo", "min"),
                ("Máximo", "max"),
                ("Média", "avg"),
                ("Mediana", "median"),
            ]
            for label, key in forecast_labels:
                val = vals.get(key)
                if val is not None:
                    p.drawString(margin_left + 20, y, f"  • {label}: {val:.2f}" if isinstance(val, (int, float)) else f"  • {label}: {val}")
                    y -= 10

            y -= 4

    # ============ VERIFICAR SE PRECISA DE NOVA PÁGINA ==============
    if y < 100:
        p.showPage()
        y = margin_top

    # ============ TEXTO EXPLICATIVO (MODELO DE FALA) ==============
    p.setFont("Helvetica-Bold", 12)
    p.drawString(margin_left, y, "ANÁLISE E EXPLICAÇÕES")
    y -= 16

    explanation = generate_report_explanation(metrics, spark_metrics, r.get("silo_name", "Silo"))
    p.setFont("Helvetica", 9)
    text_lines = explanation.split("\n")
    for line in text_lines:
        if y < 50:
            p.showPage()
            y = margin_top
        # Quebrar linhas longas
        if len(line) > 100:
            for part in [line[i:i+100] for i in range(0, len(line), 100)]:
                p.drawString(margin_left, y, part)
                y -= 11
        else:
            p.drawString(margin_left, y, line)
            y -= 11

    # ============ METEOROLOGIA 7 DIAS ==============
    try:
        met_coll = get_collection("meteorology")
        met_doc = await met_coll.find_one(
            {"silo_id": r.get("silo_id")},
            sort=[("fetched_at", -1)]
        )
        if met_doc and met_doc.get("data"):
            daily = met_doc["data"].get("daily", {})
            times = daily.get("time", [])
            tmax = daily.get("temperature_2m_max", [])
            tmin = daily.get("temperature_2m_min", [])
            precip = daily.get("precipitation_sum", [])

            if y < 150:
                p.showPage()
                y = margin_top

            p.setFont("Helvetica-Bold", 12)
            p.drawString(margin_left, y, "PREVISÃO METEOROLÓGICA - 7 DIAS")
            y -= 16

            p.setFont("Helvetica", 9)
            for i in range(min(7, len(times))):
                date_str = times[i]
                t_max = tmax[i] if i < len(tmax) else "—"
                t_min = tmin[i] if i < len(tmin) else "—"
                p_val = precip[i] if i < len(precip) else "—"

                p.drawString(
                    margin_left, y,
                    f"{date_str} | Máx {t_max}°C | Mín {t_min}°C | Precipitação {p_val} mm"
                )
                y -= 11

    except Exception as e:
        print(f"Warning: could not include meteorology: {e}")

    # ============ FINALIZAR PDF ==============
    p.showPage()
    p.save()
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=relatorio_{report_id}.pdf"},
    )