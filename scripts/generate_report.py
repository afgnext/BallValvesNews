#!/usr/bin/env python3
"""
AFG Market Intelligence — Daily Report Generator
Genera data.json (leído por index.html) y lo guarda en Neon.

Secrets requeridos en GitHub:
  ANTHROPIC_API_KEY, TAVILY_API_KEY, NEON_DATABASE_URL
  SMTP_USER, SMTP_PASS (Gmail App Password), REPORT_URL
"""
import os, json, smtplib, psycopg2
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from psycopg2.extras import Json
from datetime import date
from pathlib import Path
import requests
import anthropic

TODAY        = date.today()
ROOT         = Path(__file__).parent.parent
OUTPUT_JSON  = ROOT / "data.json"
RECIPIENTS_F = ROOT / "config" / "email_recipients.txt"
MANUAL_CLI_F = ROOT / "config" / "manual_clients.json"

ANTHROPIC_KEY = os.environ["ANTHROPIC_API_KEY"]
TAVILY_KEY    = os.environ["TAVILY_API_KEY"]
DATABASE_URL  = os.environ["NEON_DATABASE_URL"]
SMTP_USER     = os.environ.get("SMTP_USER","")   # afgnext100@gmail.com
SMTP_PASS     = os.environ.get("SMTP_PASS","")   # Gmail App Password (16 chars)
REPORT_URL    = os.environ.get("REPORT_URL","https://tu-proyecto.vercel.app")
MODEL         = "claude-sonnet-4-6"

QUERIES = [
    f"ball valve failure oil gas refinery USA {TODAY.year}",
    f"LNG project USA valves procurement contract {TODAY.year}",
    f"tariffs steel China USA valves {TODAY.year}",
    f"stainless steel supply chain shortage USA {TODAY.year}",
    f"EPC oil gas project USA refinery expansion {TODAY.year}",
    f"valve manufacturer Michigan USA oil gas {TODAY.year}",
    f"CBAM steel carbon border adjustment {TODAY.year}",
    "pipeline valve replacement maintenance USA midstream",
    "ball valve stainless steel supplier USA procurement",
    f"Section 232 steel tariff valve industry {TODAY.year}",
    "LNG terminal valve component Texas Louisiana",
    "refinery turnaround valve replacement USA",
]

# ── Neon ───────────────────────────────────────────────────────────────────────
def ensure_schema():
    conn = psycopg2.connect(DATABASE_URL)
    cur  = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id           SERIAL      PRIMARY KEY,
            report_date  DATE        NOT NULL UNIQUE,
            raw_data     JSONB       NOT NULL,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_reports_date ON reports(report_date DESC);
    """)
    conn.commit(); cur.close(); conn.close()
    print("  OK schema Neon")

def store_in_neon(data: dict):
    conn = psycopg2.connect(DATABASE_URL)
    cur  = conn.cursor()
    cur.execute("""
        INSERT INTO reports(report_date, raw_data)
        VALUES(%s,%s)
        ON CONFLICT(report_date) DO UPDATE
          SET raw_data=EXCLUDED.raw_data, updated_at=NOW()
    """, (TODAY, Json(data)))
    conn.commit(); cur.close(); conn.close()
    print("  OK guardado en Neon")

# ── Web search ─────────────────────────────────────────────────────────────────
def search(query: str) -> list[dict]:
    try:
        r = requests.post("https://api.tavily.com/search", timeout=20, json={
            "api_key": TAVILY_KEY, "query": query,
            "search_depth": "basic", "max_results": 5,
        })
        r.raise_for_status()
        return r.json().get("results", [])
    except Exception as e:
        print(f"  WARN search: {e}"); return []

def run_searches() -> list[dict]:
    seen, out = set(), []
    for q in QUERIES:
        print(f"  >> {q[:60]}")
        for item in search(q):
            url = item.get("url","")
            if url and url not in seen:
                seen.add(url); out.append(item)
    print(f"  OK {len(out)} fuentes"); return out

# ── Claude analysis ────────────────────────────────────────────────────────────
SYSTEM = """Analista senior de market intelligence en oil & gas y supply chain.
Cliente: AFG (Alcorta Forging Group), fabrica bolas de acero inox ~4" ~10kg para
valvulas de bola oil & gas. TIENE PLANTA EN MICHIGAN, USA. Por tanto:
- NO hay barrera logistica desde Europa al mercado USA
- Los riesgos reales son: certificaciones API/NACE, ciclos aprobacion EPC,
  competencia china post-arancel, tiempo de homologacion con majors.
Devuelve UNICAMENTE JSON valido sin texto adicional."""

PROMPT = """Fecha: {today}

Resultados de busqueda:
{context}

Devuelve este JSON exacto:
{{
  "date": "{today}",
  "summary": {{
    "key_signal": "<senal mas importante en 1 frase>",
    "market_temp": <0-100>
  }},
  "opportunities": [{{
    "title": "", "company": "", "location": "", "type": "",
    "description": "", "probability": "Alta|Media|Baja",
    "tags": [], "source_url": "", "source_title": "", "date": ""
  }}],
  "alerts": [{{
    "level": "Critica|Alta|Media", "title": "", "body": "",
    "source_url": "", "source_title": ""
  }}],
  "projects": [{{
    "name": "", "phase": "planificacion|ejecucion|operativo",
    "companies": "", "location": "", "description": "",
    "capex": "", "source_url": ""
  }}],
  "risks": [{{
    "title": "", "impact": "Alto|Medio|Bajo",
    "description": "", "mitigation": ""
  }}],
  "actions": [{{
    "target": "", "type": "urgente|distribucion|partnership|comunicacion",
    "description": "", "signals": [], "url": ""
  }}],
  "potential_clients": [{{
    "name": "", "type": "EPC|Operator|Distributor|OEM|MRO",
    "url": "", "city": "", "lat": 0.0, "lng": 0.0,
    "reason": "", "priority": "Alta|Media|Baja"
  }}]
}}

Minimo: 4 oportunidades, 3 alertas, 3 proyectos, 3 riesgos, 4 acciones, 6 clientes.
NUNCA incluir coste logistico desde Europa como riesgo (AFG tiene planta Michigan).
Solo hallazgos respaldados por los resultados. Solo JSON."""

def analyze(results: list[dict]) -> dict:
    ctx = "\n\n---\n\n".join(
        f"TITULO: {r.get('title','')}\nURL: {r.get('url','')}\n"
        f"FECHA: {r.get('published_date','')}\nCONT: {r.get('content','')[:600]}"
        for r in results[:40]
    )
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    msg = client.messages.create(
        model=MODEL, max_tokens=16000,
        system=SYSTEM,
        messages=[{"role":"user","content":PROMPT.format(
            today=TODAY.strftime("%d %B %Y"), context=ctx
        )}],
    )
    raw = msg.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```",2)[1]
        if raw.startswith("json"): raw = raw[4:]
        raw = raw.rsplit("```",1)[0]
    return json.loads(raw.strip())

# ── Manual clients ─────────────────────────────────────────────────────────────
def load_manual_clients() -> list[dict]:
    if not MANUAL_CLI_F.exists(): return []
    try:
        data = json.loads(MANUAL_CLI_F.read_text(encoding="utf-8"))
        clients = data.get("clients", [])
        for c in clients: c["_manual"] = True
        return clients
    except Exception as e:
        print(f"  WARN manual_clients: {e}"); return []

# ── Email vía Gmail SMTP ────────────────────────────────────────────────────────
def load_recipients() -> list[str]:
    if not RECIPIENTS_F.exists(): return []
    return [l.strip() for l in RECIPIENTS_F.read_text().splitlines()
            if l.strip() and not l.startswith("#") and "@" in l]

def send_email(recipients, key_signal, n_opps, n_projects):
    if not recipients: print("  WARN sin destinatarios"); return
    if not all([SMTP_USER, SMTP_PASS]):
        print("  WARN Gmail SMTP no configurado"); return
    today_str = TODAY.strftime("%d %B %Y")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"AFG Market Radar actualizado: {today_str}"
    msg["From"]    = f"AFG Intelligence <{SMTP_USER}>"
    msg["To"]      = ", ".join(recipients)
    body = f"""<html><body style="font-family:Arial,sans-serif;background:#f5f5f5;padding:20px">
<div style="max-width:580px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.1)">
  <div style="background:#0d1117;padding:24px 28px">
    <span style="background:#e8a225;color:#000;font-weight:800;padding:5px 10px;border-radius:6px;font-size:13px">AFG</span>
    <span style="color:#e6edf3;font-size:16px;font-weight:600;margin-left:10px">Market Intelligence Radar</span>
    <p style="color:#7d8590;margin:6px 0 0;font-size:12px">Stainless Steel Balls · Oil &amp; Gas USA · Planta Michigan</p>
  </div>
  <div style="padding:24px 28px">
    <p style="color:#333;font-size:14px">El Radar ha sido actualizado con la inteligencia del dia.</p>
    <div style="background:#f8f9fa;border-left:4px solid #e8a225;padding:14px 18px;border-radius:0 8px 8px 0;margin:18px 0">
      <div style="font-size:10px;font-weight:700;text-transform:uppercase;color:#888;margin-bottom:4px">Senal clave del dia</div>
      <div style="font-size:14px;font-weight:600;color:#111">{key_signal}</div>
    </div>
    <div style="display:flex;gap:12px;margin-bottom:20px">
      <div style="flex:1;background:#fff3e0;border-radius:8px;padding:14px;text-align:center">
        <div style="font-size:26px;font-weight:800;color:#e8a225">{n_opps}</div>
        <div style="font-size:11px;color:#888;text-transform:uppercase">Oportunidades</div>
      </div>
      <div style="flex:1;background:#e3f2fd;border-radius:8px;padding:14px;text-align:center">
        <div style="font-size:26px;font-weight:800;color:#1f6feb">{n_projects}</div>
        <div style="font-size:11px;color:#888;text-transform:uppercase">Proyectos</div>
      </div>
    </div>
    <a href="{REPORT_URL}" style="display:block;background:#e8a225;color:#000;text-align:center;padding:13px;border-radius:8px;font-weight:700;font-size:14px;text-decoration:none">Ver informe completo</a>
  </div>
  <div style="background:#f8f9fa;padding:14px 28px;text-align:center;font-size:11px;color:#aaa">{today_str} · AFG Market Intelligence</div>
</div></body></html>"""
    msg.attach(MIMEText(body, "html"))
    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as s:
            s.ehlo(); s.starttls(); s.login(SMTP_USER, SMTP_PASS)
            s.sendmail(SMTP_USER, recipients, msg.as_string())
        print(f"  OK email a {len(recipients)} destinatarios")
    except Exception as e:
        print(f"  WARN email: {e}")

# ── Main ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"\n{'='*55}\n  AFG Market Intelligence - {TODAY}\n{'='*55}\n")

    print("[1/7] Schema Neon...")
    ensure_schema()

    print("\n[2/7] Buscando en la web...")
    results = run_searches()

    print("\n[3/7] Analizando con Claude...")
    data = analyze(results)
    opps     = data.get("opportunities",[])
    projects = data.get("projects",[])
    clients  = data.get("potential_clients",[])
    print(f"  OK {len(opps)} oport | {len(projects)} proyectos | {len(clients)} clientes")

    print("\n[4/7] Clientes manuales...")
    manual = load_manual_clients()
    data["manual_clients"] = manual
    data["sources"] = [{"title": r.get("title",""), "url": r.get("url","")}
                       for r in results[:15] if r.get("url")]
    print(f"  OK {len(manual)} manuales")

    print("\n[5/7] Guardando en Neon...")
    store_in_neon(data)

    print("\n[6/7] Escribiendo data.json...")
    OUTPUT_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  OK {OUTPUT_JSON}")

    print("\n[7/7] Enviando email...")
    send_email(
        load_recipients(),
        data.get("summary",{}).get("key_signal",""),
        len(opps), len(projects)
    )

    print(f"\n{'='*55}\n  Completado\n{'='*55}\n")
