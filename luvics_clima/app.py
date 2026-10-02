#!/usr/bin/env python3
"""
Luvics Clima no Ponto — API (Render / local)
============================================
Local:
  pip install -r requirements.txt
  python app.py
  -> http://127.0.0.1:5050

Render:
  Start command: gunicorn app:app
  Env vars: EMAIL_HOST, EMAIL_PORT, EMAIL_USER, EMAIL_PASS, EMAIL_FROM
"""

from __future__ import annotations

import io
import math
import os
import smtplib
from datetime import datetime, timedelta
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import requests
from flask import Flask, jsonify, request, send_file, send_from_directory
from flask_cors import CORS
from fpdf import FPDF
from PIL import Image, ImageDraw
from staticmap import CircleMarker, Line, StaticMap

ROOT = Path(__file__).parent
STATIC = ROOT / "static"
OUTPUT = ROOT / "output"
OUTPUT.mkdir(exist_ok=True)

# =============================================================================
# E-MAIL — no Render use Environment Variables (mais seguro).
# Localmente pode preencher aqui OU usar env.
# =============================================================================
EMAIL_CONFIG = {
    "HOST": "smtp.gmail.com",
    "PORT": 587,
    "USER": "",  # ex: seu@gmail.com
    "PASS": "",  # senha de app
    "FROM": "",
}
# =============================================================================

USER_AGENT = "TechLuvics-ClimaNoPonto/1.0 (contato@techluvics.com.br)"

app = Flask(__name__, static_folder=str(STATIC), static_url_path="")
# Libera o front no GitHub Pages / dominio tech.luvics
CORS(app, resources={r"/api/*": {"origins": "*"}})


def ascii_safe(text) -> str:
    if text is None:
        return "-"
    s = str(text)
    repl = {
        "—": "-", "–": "-", "−": "-",
        "°": "C", "≤": "<=", "≥": ">=",
        "á": "a", "à": "a", "ã": "a", "â": "a", "ä": "a",
        "é": "e", "ê": "e", "è": "e",
        "í": "i", "ì": "i",
        "ó": "o", "ô": "o", "õ": "o", "ò": "o",
        "ú": "u", "ù": "u", "ü": "u",
        "ç": "c", "ñ": "n",
        "Á": "A", "À": "A", "Ã": "A", "Â": "A",
        "É": "E", "Ê": "E", "Í": "I",
        "Ó": "O", "Ô": "O", "Õ": "O", "Ú": "U", "Ç": "C",
        "•": "-", "·": "-",
        "“": '"', "”": '"', "‘": "'", "’": "'",
    }
    for a, b in repl.items():
        s = s.replace(a, b)
    return s.encode("latin-1", errors="replace").decode("latin-1")


def _email_settings():
    host = os.environ.get("EMAIL_HOST") or EMAIL_CONFIG.get("HOST") or "smtp.gmail.com"
    port = int(os.environ.get("EMAIL_PORT") or EMAIL_CONFIG.get("PORT") or 587)
    user = (os.environ.get("EMAIL_USER") or EMAIL_CONFIG.get("USER") or "").strip()
    password = (os.environ.get("EMAIL_PASS") or EMAIL_CONFIG.get("PASS") or "").strip()
    from_addr = (os.environ.get("EMAIL_FROM") or EMAIL_CONFIG.get("FROM") or user).strip()
    if password.lower().startswith("xxxx"):
        password = ""
    return host, port, user, password, from_addr


def email_configured() -> bool:
    _, _, user, password, _ = _email_settings()
    return bool(user and password)


def send_report_email(to_email: str, pdf_bytes: bytes, filename: str, mode: str, lat: float, lon: float) -> None:
    host, port, user, password, from_addr = _email_settings()
    if not user or not password:
        raise RuntimeError("E-mail nao configurado. Defina EMAIL_USER e EMAIL_PASS no Render ou no EMAIL_CONFIG.")
    if not to_email or "@" not in to_email:
        raise RuntimeError("E-mail do destinatario invalido.")

    if mode == "free":
        subject = "Seu relatorio GRATIS - Luvics Clima no Ponto"
        body = (
            "Ola!\n\n"
            "Segue o relatorio GRATUITO do Luvics Clima no Ponto.\n"
            f"Ponto: {lat:.6f}, {lon:.6f}\n\n"
            "Esta versao inclui apenas temperatura atual e mapa de 1 km.\n"
            "Para previsao completa, chuva, vento, historico e envio diario automatico:\n"
            "assine a partir de R$ 9,90/mes (1 ponto).\n\n"
            "5 pontos R$ 19,90 | 10 pontos R$ 29,90 | extra +R$ 5/ponto\n\n"
            "Tech.luvics - Inteligencia de Ativos & IA\n"
            "https://tech.luvics.com.br\n"
        )
    else:
        subject = "Seu relatorio COMPLETO - Luvics Clima no Ponto"
        body = (
            "Ola!\n\n"
            "Segue o relatorio COMPLETO (simulacao do plano pago).\n"
            f"Ponto: {lat:.6f}, {lon:.6f}\n\n"
            "Inclui previsao 7 dias, chuva, vento, umidade e historico.\n\n"
            "Tech.luvics - Inteligencia de Ativos & IA\n"
            "https://tech.luvics.com.br\n"
        )

    msg = MIMEMultipart()
    msg["From"] = from_addr
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    part = MIMEBase("application", "pdf")
    part.set_payload(pdf_bytes)
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
    msg.attach(part)

    with smtplib.SMTP(host, port, timeout=30) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(user, password)
        server.sendmail(from_addr, [to_email], msg.as_string())


def weather_code_label(code):
    table = {
        0: "Ceu limpo", 1: "Principalmente limpo", 2: "Parcialmente nublado", 3: "Nublado",
        45: "Nevoeiro", 48: "Nevoeiro", 51: "Garoa fraca", 61: "Chuva fraca",
        63: "Chuva moderada", 65: "Chuva forte", 80: "Pancadas", 95: "Trovoada",
    }
    try:
        return table.get(int(code), f"Codigo {code}")
    except Exception:
        return "-"


def fetch_climate(lat: float, lon: float) -> dict:
    fc = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m,precipitation,weather_code,wind_speed_10m",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,wind_speed_10m_max",
            "timezone": "America/Sao_Paulo",
            "forecast_days": 7,
        },
        timeout=30,
    )
    fc.raise_for_status()
    forecast = fc.json()

    end = datetime.utcnow().date() - timedelta(days=1)
    start = end - timedelta(days=30)
    hist = {}
    try:
        ha = requests.get(
            "https://archive-api.open-meteo.com/v1/archive",
            params={
                "latitude": lat,
                "longitude": lon,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
                "timezone": "America/Sao_Paulo",
            },
            timeout=30,
        )
        if ha.status_code == 200:
            hist = ha.json()
    except Exception:
        pass
    return {"forecast": forecast, "history": hist}


def summarize(data: dict) -> dict:
    fc = data.get("forecast") or {}
    cur = fc.get("current") or {}
    daily = fc.get("daily") or {}
    hist = (data.get("history") or {}).get("daily") or {}
    s = {
        "temp_now": cur.get("temperature_2m"),
        "humidity": cur.get("relative_humidity_2m"),
        "precip_now": cur.get("precipitation"),
        "wind": cur.get("wind_speed_10m"),
        "weather": weather_code_label(cur.get("weather_code")),
        "days": [],
        "hist_tmin": None,
        "hist_tmax": None,
        "hist_precip": None,
        "nights_cold": 0,
    }
    times = daily.get("time") or []
    for i, day in enumerate(times):
        s["days"].append({
            "date": day,
            "tmax": (daily.get("temperature_2m_max") or [None])[i],
            "tmin": (daily.get("temperature_2m_min") or [None])[i],
            "precip": (daily.get("precipitation_sum") or [None])[i],
            "pop": (daily.get("precipitation_probability_max") or [None])[i],
            "wind": (daily.get("wind_speed_10m_max") or [None])[i],
        })
    tmin_h = [v for v in (hist.get("temperature_2m_min") or []) if v is not None]
    tmax_h = [v for v in (hist.get("temperature_2m_max") or []) if v is not None]
    pr_h = [v for v in (hist.get("precipitation_sum") or []) if v is not None]
    if tmin_h:
        s["hist_tmin"] = min(tmin_h)
        s["nights_cold"] = sum(1 for v in tmin_h if v <= 5)
    if tmax_h:
        s["hist_tmax"] = max(tmax_h)
    if pr_h:
        s["hist_precip"] = round(sum(pr_h), 1)
    return s


def make_map_png(lat: float, lon: float, radius_m: int = 1000) -> Path:
    path = OUTPUT / f"map_{lat:.4f}_{lon:.4f}_{radius_m}.png"
    m = StaticMap(800, 500, url_template="https://tile.openstreetmap.org/{z}/{x}/{y}.png")
    n = 64
    pts = []
    for i in range(n + 1):
        ang = 2 * math.pi * i / n
        dlat = (radius_m / 111320.0) * math.cos(ang)
        dlon = (radius_m / (111320.0 * math.cos(math.radians(lat)))) * math.sin(ang)
        pts.append((lon + dlon, lat + dlat))
    for i in range(len(pts) - 1):
        m.add_line(Line([pts[i], pts[i + 1]], "#0B4624", 2))
    m.add_marker(CircleMarker((lon, lat), "#E11D48", 14))
    try:
        img = m.render(zoom=14)
    except Exception:
        img = Image.new("RGB", (800, 500), (240, 240, 240))
        d = ImageDraw.Draw(img)
        d.text((20, 20), f"Mapa indisponivel | {lat:.5f}, {lon:.5f}", fill=(0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle([10, 10, 280, 48], fill=(255, 255, 255), outline=(20, 20, 20))
    draw.text((18, 18), f"Raio 1 km | {lat:.5f}, {lon:.5f}", fill=(0, 0, 0))
    img.save(str(path))
    return path


def _cell(pdf, text, ln=1, bold=False, size=10, center=False):
    pdf.set_font("Helvetica", "B" if bold else "", size)
    pdf.cell(0, 5 if size <= 10 else 7, ascii_safe(text), ln=ln, align="C" if center else "L")


def build_pdf_free(lat, lon, email, summary, map_path: Path) -> bytes:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.add_page()
    _cell(pdf, "Tech.luvics | Luvics Clima no Ponto", bold=True, size=14, center=True)
    _cell(pdf, "VERSAO GRATUITA (limitada)", bold=True, size=11, center=True)
    _cell(pdf, datetime.now().strftime("%d/%m/%Y %H:%M"), size=9, center=True)
    pdf.ln(4)

    _cell(pdf, "1. Seu ponto", bold=True, size=12)
    _cell(pdf, f"Latitude:  {lat:.6f}")
    _cell(pdf, f"Longitude: {lon:.6f}")
    if email:
        _cell(pdf, f"E-mail informado: {email}")
    pdf.ln(2)

    _cell(pdf, "2. O que voce recebe no plano gratis", bold=True, size=12)
    _cell(pdf, f"Temperatura atual no ponto: {summary.get('temp_now')} C", bold=True, size=12)
    _cell(pdf, f"Condicao (resumo): {summary.get('weather')}")
    pdf.ln(2)

    _cell(pdf, "3. Mapa de referencia (raio 1 km)", bold=True, size=12)
    if map_path.exists():
        pdf.image(str(map_path), w=180)
    pdf.ln(3)

    pdf.set_fill_color(255, 247, 237)
    pdf.rect(10, pdf.get_y(), 190, 52, style="F")
    y = pdf.get_y() + 4
    pdf.set_xy(14, y)
    _cell(pdf, "ESTE RELATORIO ESTA INCOMPLETO DE PROPOSITO", bold=True, size=11)
    pdf.set_x(14)
    _cell(pdf, "No plano gratis voce ve apenas temperatura atual + mapa da regiao.")
    pdf.set_x(14)
    _cell(pdf, "Bloqueado: previsao 7 dias, chuva, vento, umidade, historico 30 dias,")
    pdf.set_x(14)
    _cell(pdf, "alertas de frio e envio automatico todo dia no seu e-mail.")
    pdf.set_x(14)
    _cell(pdf, "Desbloqueie a partir de R$ 9,90/mes (1 ponto diario).", bold=True)
    pdf.set_x(14)
    _cell(pdf, "5 pontos R$ 19,90 | 10 pontos R$ 29,90 | extra +R$ 5/ponto")
    pdf.ln(8)

    _cell(pdf, "4. Fontes", bold=True, size=12)
    pdf.multi_cell(
        0, 4.5,
        ascii_safe(
            "Open-Meteo (clima). OpenStreetMap (mapa e busca). "
            "Material orientativo - nao substitui ART ou laudo agronomico oficial. tech.luvics.com.br"
        ),
    )

    buf = io.BytesIO()
    pdf.output(buf)
    return buf.getvalue()


def build_pdf_full(lat, lon, email, summary, map_path: Path) -> bytes:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.add_page()
    _cell(pdf, "Tech.luvics | Luvics Clima no Ponto", bold=True, size=14, center=True)
    _cell(pdf, "RELATORIO COMPLETO (plano pago - simulacao de teste)", bold=True, size=11, center=True)
    _cell(pdf, datetime.now().strftime("%d/%m/%Y %H:%M"), size=9, center=True)
    pdf.ln(3)

    _cell(pdf, "1. Ponto monitorado", bold=True, size=12)
    _cell(pdf, f"Lat {lat:.6f} | Lon {lon:.6f}")
    if email:
        _cell(pdf, f"E-mail: {email}")
    pdf.ln(2)

    _cell(pdf, "2. Condicao atual", bold=True, size=12)
    _cell(pdf, f"Temperatura: {summary.get('temp_now')} C")
    _cell(pdf, f"Umidade: {summary.get('humidity')} %")
    _cell(pdf, f"Precipitacao (agora): {summary.get('precip_now')} mm")
    _cell(pdf, f"Vento: {summary.get('wind')} km/h")
    _cell(pdf, f"Condicao: {summary.get('weather')}")
    pdf.ln(2)

    _cell(pdf, "3. Previsao 7 dias", bold=True, size=12)
    for d in summary.get("days") or []:
        _cell(
            pdf,
            f"{d['date']}: Tmin {d['tmin']}C | Tmax {d['tmax']}C | "
            f"Chuva {d['precip']}mm | Prob {d['pop']}% | Vento {d['wind']}km/h",
            size=9,
        )
    pdf.ln(2)

    _cell(pdf, "4. Historico 30 dias", bold=True, size=12)
    _cell(pdf, f"Tmin observada: {summary.get('hist_tmin')} C")
    _cell(pdf, f"Tmax observada: {summary.get('hist_tmax')} C")
    _cell(pdf, f"Chuva acumulada: {summary.get('hist_precip')} mm")
    _cell(pdf, f"Noites com Tmin <= 5C: {summary.get('nights_cold')}")
    pdf.ln(2)

    _cell(pdf, "5. Mapa (raio 1 km)", bold=True, size=12)
    if map_path.exists():
        pdf.image(str(map_path), w=180)
    pdf.ln(2)

    _cell(pdf, "6. Interpretacao orientativa", bold=True, size=12)
    pdf.multi_cell(
        0, 4.5,
        ascii_safe(
            "Dados de modelo meteorologico de superficie (Open-Meteo). "
            "Use como apoio operacional no ponto (sede/talhao). "
            "Nao substitui laudo agronomico, ART ou cobertura de seguro. "
            "Em risco de frio, combine com observacao local e vento calmo."
        ),
    )
    pdf.ln(2)
    _cell(pdf, "tech.luvics.com.br | Inteligencia de Ativos & IA", bold=True, size=9)

    buf = io.BytesIO()
    pdf.output(buf)
    return buf.getvalue()


@app.get("/api/health")
def api_health():
    return jsonify({"ok": True, "service": "luvics-clima", "email": email_configured()})


@app.get("/api/email-status")
def api_email_status():
    host, port, user, password, _ = _email_settings()
    return jsonify({
        "configured": bool(user and password),
        "host": host,
        "port": port,
        "user": (user[:3] + "***") if user else "",
    })


@app.get("/api/geocode")
def api_geocode():
    q = (request.args.get("q") or "").strip()
    if len(q) < 3:
        return jsonify({"results": []})
    r = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": q, "format": "json", "limit": 5, "countrycodes": "br", "addressdetails": 1},
        headers={"User-Agent": USER_AGENT},
        timeout=20,
    )
    r.raise_for_status()
    results = [
        {"display": i.get("display_name", ""), "lat": float(i["lat"]), "lon": float(i["lon"])}
        for i in r.json()
    ]
    return jsonify({"results": results})


@app.post("/api/report")
def api_report():
    body = request.get_json(force=True, silent=True) or {}
    try:
        lat = float(body.get("lat"))
        lon = float(body.get("lon"))
    except (TypeError, ValueError):
        return jsonify({"error": "lat/lon invalidos"}), 400
    email = (body.get("email") or "").strip()
    mode = (body.get("mode") or "free").lower()
    if mode not in ("free", "full"):
        mode = "free"

    try:
        raw = fetch_climate(lat, lon)
        summary = summarize(raw)
        map_path = make_map_png(lat, lon, 1000)
        if mode == "free":
            pdf_bytes = build_pdf_free(lat, lon, email, summary, map_path)
            fname = "luvics_clima_GRATIS.pdf"
        else:
            pdf_bytes = build_pdf_full(lat, lon, email, summary, map_path)
            fname = "luvics_clima_COMPLETO.pdf"

        (OUTPUT / f"{mode}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf").write_bytes(pdf_bytes)

        emailed = False
        email_error = None
        if email:
            if not email_configured():
                email_error = (
                    "E-mail do destinatario ok, mas SMTP nao configurado. "
                    "Defina EMAIL_USER e EMAIL_PASS no Render."
                )
            else:
                try:
                    send_report_email(email, pdf_bytes, fname, mode, lat, lon)
                    emailed = True
                except Exception as mail_err:
                    email_error = str(mail_err)

        resp = send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=fname,
        )
        resp.headers["X-Luvics-Emailed"] = "1" if emailed else "0"
        if email_error:
            resp.headers["X-Luvics-Email-Error"] = email_error[:200]
        # Expoe headers customizados ao browser (CORS)
        resp.headers["Access-Control-Expose-Headers"] = "X-Luvics-Emailed, X-Luvics-Email-Error"
        return resp
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/")
def index():
    return send_from_directory(STATIC, "index.html")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    print("=" * 60)
    print("Luvics Clima no Ponto")
    print(f"Local: http://127.0.0.1:{port}")
    print(f"E-mail configurado: {email_configured()}")
    print("=" * 60)
    app.run(host="0.0.0.0", port=port, debug=False)
