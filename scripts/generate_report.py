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
CHAT_USERS_F = ROOT / "config" / "chat_users.json"

ANTHROPIC_KEY = os.environ["ANTHROPIC_API_KEY"]
TAVILY_KEY    = os.environ["TAVILY_API_KEY"]
DATABASE_URL  = os.environ["NEON_DATABASE_URL"]
SMTP_USER     = os.environ.get("SMTP_USER","")   # afgnext100@gmail.com
SMTP_PASS     = os.environ.get("SMTP_PASS","")   # Gmail App Password (16 chars)
REPORT_URL    = os.environ.get("REPORT_URL","https://tu-proyecto.vercel.app")
OPENAI_KEY    = os.environ.get("OPENAI_API_KEY","")
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
            report_date  DATE        NOT NULL,
            lang         TEXT        NOT NULL DEFAULT 'es',
            raw_data     JSONB       NOT NULL,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_reports_date ON reports(report_date DESC);

        CREATE TABLE IF NOT EXISTS messages (
            id         SERIAL       PRIMARY KEY,
            user_name  TEXT         NOT NULL,
            avatar     TEXT         NOT NULL DEFAULT '👤',
            message    TEXT         NOT NULL,
            created_at TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_messages_date ON messages(created_at DESC);

        CREATE TABLE IF NOT EXISTS clients (
            id             SERIAL       PRIMARY KEY,
            name           TEXT         NOT NULL,
            type           TEXT         NOT NULL DEFAULT 'EPC',
            url            TEXT,
            city           TEXT,
            lat            FLOAT,
            lng            FLOAT,
            notes          TEXT,
            priority       TEXT         NOT NULL DEFAULT 'Media',
            priority_order INT          NOT NULL DEFAULT 2,
            source         TEXT         NOT NULL DEFAULT 'manual',
            created_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        );
    """)
    conn.commit()

    # ── Migraciones para bases de datos ya existentes ──────────────────────────
    # Añadir columna lang a reports si no existe
    cur.execute("ALTER TABLE reports ADD COLUMN IF NOT EXISTS lang TEXT NOT NULL DEFAULT 'es'")
    conn.commit()

    # Actualizar unique constraint: de solo report_date → (report_date, lang)
    cur.execute("""
        DO $$
        BEGIN
            -- Eliminar constraint antiguo de una sola columna
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'reports_report_date_key'
                  AND conrelid = 'reports'::regclass
            ) THEN
                ALTER TABLE reports DROP CONSTRAINT reports_report_date_key;
            END IF;
            -- Añadir constraint compuesto si no existe
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'reports_date_lang_unique'
                  AND conrelid = 'reports'::regclass
            ) THEN
                ALTER TABLE reports
                    ADD CONSTRAINT reports_date_lang_unique UNIQUE (report_date, lang);
            END IF;
        END $$
    """)
    conn.commit()

    # Añadir columna source a clients si la tabla ya existía sin ella
    cur.execute("ALTER TABLE clients ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'manual'")
    conn.commit()

    # Migrar clientes de manual_clients.json si la tabla está vacía
    cur.execute("SELECT COUNT(*) FROM clients")
    if cur.fetchone()[0] == 0 and MANUAL_CLI_F.exists():
        try:
            data = json.loads(MANUAL_CLI_F.read_text(encoding="utf-8"))
            for c in data.get("clients", []):
                prio = c.get("priority", "Media")
                porder = {"Alta":1,"Media":2,"Baja":3}.get(prio, 2)
                cur.execute("""
                    INSERT INTO clients (name, type, url, city, lat, lng, notes, priority, priority_order, source)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'manual')
                """, (c.get("name",""), c.get("type","EPC"), c.get("url"),
                      c.get("city"), c.get("lat"), c.get("lng"),
                      c.get("notes"), prio, porder))
            conn.commit()
            print(f"  OK {len(data.get('clients',[]))} clientes migrados desde manual_clients.json")
        except Exception as e:
            print(f"  WARN migración clientes: {e}")

    cur.close(); conn.close()
    print("  OK schema Neon")

def store_in_neon(data: dict, lang: str = 'es'):
    conn = psycopg2.connect(DATABASE_URL)
    cur  = conn.cursor()
    cur.execute("""
        INSERT INTO reports(report_date, lang, raw_data)
        VALUES(%s, %s, %s)
        ON CONFLICT(report_date, lang) DO UPDATE
          SET raw_data=EXCLUDED.raw_data, updated_at=NOW()
    """, (TODAY, lang, Json(data)))
    conn.commit(); cur.close(); conn.close()
    print(f"  OK guardado en Neon [{lang.upper()}]")

def load_previous_report() -> dict:
    """Carga el informe del día anterior (versión ES) para evitar repetir contenido."""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur  = conn.cursor()
        cur.execute("""
            SELECT raw_data FROM reports
            WHERE report_date < %s AND lang = 'es'
            ORDER BY report_date DESC LIMIT 1
        """, (TODAY,))
        row = cur.fetchone()
        cur.close(); conn.close()
        if row:
            print("  OK informe anterior cargado para deduplicación")
            return row[0]
    except Exception as e:
        print(f"  WARN load_previous_report: {e}")
    return {}

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
    "url": "<URL OFICIAL de la web corporativa de la empresa, NO la del articulo. Ej: https://www.saipem.com>",
    "city": "", "lat": 0.0, "lng": 0.0,
    "reason": "", "priority": "Alta|Media|Baja"
  }}]
}}

Minimo: 4 oportunidades, 3 alertas, 3 proyectos, 3 riesgos, 4 acciones, 6 clientes.
NUNCA incluir coste logistico desde Europa como riesgo (AFG tiene planta Michigan).
{dedup_section}
Solo hallazgos respaldados por los resultados. Solo JSON."""

def build_dedup_section(prev: dict) -> str:
    """Genera el bloque de deduplicación a partir del informe anterior."""
    if not prev: return ""
    lines = ["IMPORTANTE — Ya se reportaron ayer los siguientes items. NO los repitas, busca contenido NUEVO:"]
    for o in prev.get("opportunities", [])[:6]:
        lines.append(f"  - Oportunidad ya vista: {o.get('title','')} ({o.get('company','')})")
    for a in prev.get("alerts", [])[:4]:
        lines.append(f"  - Alerta ya vista: {a.get('title','')}")
    for p in prev.get("projects", [])[:4]:
        lines.append(f"  - Proyecto ya visto: {p.get('name','')}")
    return "\n".join(lines)

def analyze(results: list[dict], prev_report: dict = None) -> dict:
    ctx = "\n\n---\n\n".join(
        f"TITULO: {r.get('title','')}\nURL: {r.get('url','')}\n"
        f"FECHA: {r.get('published_date','')}\nCONT: {r.get('content','')[:600]}"
        for r in results[:40]
    )
    dedup = build_dedup_section(prev_report or {})
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    msg = client.messages.create(
        model=MODEL, max_tokens=16000,
        system=SYSTEM,
        messages=[{"role":"user","content":PROMPT.format(
            today=TODAY.strftime("%d %B %Y"), context=ctx,
            dedup_section=dedup
        )}],
    )
    raw = msg.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```",2)[1]
        if raw.startswith("json"): raw = raw[4:]
        raw = raw.rsplit("```",1)[0]
    return json.loads(raw.strip())

# ── Upsert AI clients en Neon ──────────────────────────────────────────────────
def upsert_ai_clients(ai_clients: list[dict]) -> int:
    """Añade a la BD los clientes encontrados por la IA que no existan ya (por nombre)."""
    if not ai_clients: return 0
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur  = conn.cursor()
        added = 0
        for c in ai_clients:
            name = (c.get("name") or "").strip()
            if not name: continue
            cur.execute("SELECT id FROM clients WHERE LOWER(name) = LOWER(%s)", (name,))
            if cur.fetchone(): continue   # ya existe
            prio   = c.get("priority","Media")
            porder = {"Alta":1,"Media":2,"Baja":3}.get(prio, 2)
            cur.execute("""
                INSERT INTO clients (name, type, url, city, lat, lng, notes, priority, priority_order, source)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'ai')
            """, (name, c.get("type","EPC"), c.get("url"), c.get("city"),
                  c.get("lat"), c.get("lng"), c.get("reason"), prio, porder))
            added += 1
        conn.commit(); cur.close(); conn.close()
        return added
    except Exception as e:
        print(f"  WARN upsert_ai_clients: {e}"); return 0

# ── Traducción EN con OpenAI ───────────────────────────────────────────────────
def translate_to_english(data_es: dict) -> dict | None:
    """Traduce el informe JSON de español a inglés usando GPT-4o-mini.
    Preserva los valores de enums usados como clases CSS (Alta, Media, Baja, etc.)"""
    if not OPENAI_KEY:
        print("  WARN OPENAI_API_KEY no configurado — versión EN omitida")
        return None

    system = (
        "You are a professional translator for oil & gas market intelligence reports. "
        "Translate Spanish text to English inside the JSON I provide. Strict rules:\n"
        "1. Translate ONLY these human-readable fields: title, description, body, reason, "
        "   notes, mitigation, key_signal, signals (array items), source_title, companies, "
        "   capex, target, tags (array items).\n"
        "2. NEVER translate: JSON keys, urls, source_url, company names, proper nouns, "
        "   city names, country names, date strings, numeric values.\n"
        "3. KEEP EXACTLY these enum values unchanged (used as CSS class identifiers):\n"
        "   - probability: Alta | Media | Baja\n"
        "   - impact:      Alto | Medio | Bajo\n"
        "   - level:       Critica | Alta | Media\n"
        "   - phase:       planificacion | ejecucion | operativo\n"
        "   - type (actions): urgente | distribucion | partnership | comunicacion\n"
        "   - type (clients): EPC | Operator | Distributor | OEM | MRO | BallMfg\n"
        "   - priority:    Alta | Media | Baja\n"
        "4. Return ONLY valid JSON with exactly the same structure and keys."
    )

    headers = {"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"}
    body = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": json.dumps(data_es, ensure_ascii=False)},
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    try:
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers, json=body, timeout=120
        )
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"].strip()
        result = json.loads(content)
        print(f"  OK traducción EN generada ({len(content):,} chars)")
        return result
    except Exception as e:
        print(f"  WARN translate_to_english: {e}")
        return None


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

    print("[1/8] Schema Neon...")
    ensure_schema()

    print("\n[2/8] Buscando en la web...")
    results = run_searches()

    print("\n[3/8] Analizando con Claude (ES)...")
    prev_report = load_previous_report()
    data = analyze(results, prev_report)
    opps     = data.get("opportunities",[])
    projects = data.get("projects",[])
    clients  = data.get("potential_clients",[])
    print(f"  OK {len(opps)} oport | {len(projects)} proyectos | {len(clients)} clientes")

    print("\n[4/8] Guardando clientes IA en Neon y cargando usuarios chat...")
    nuevos = upsert_ai_clients(data.get("potential_clients", []))
    data["sources"] = [{"title": r.get("title",""), "url": r.get("url","")}
                       for r in results[:15] if r.get("url")]
    try:
        chat_data = json.loads(CHAT_USERS_F.read_text(encoding="utf-8"))
        data["chat_users"] = chat_data.get("users", [])
    except Exception:
        data["chat_users"] = []
    print(f"  OK {nuevos} clientes nuevos añadidos a BD | {len(data['chat_users'])} usuarios chat")

    print("\n[5/8] Traduciendo a inglés con GPT-4o-mini...")
    data_en = translate_to_english(data)

    print("\n[6/8] Guardando en Neon (ES + EN)...")
    store_in_neon(data, lang='es')
    if data_en:
        store_in_neon(data_en, lang='en')
    else:
        print("  SKIP versión EN no disponible (sin OPENAI_API_KEY o error de traducción)")

    print("\n[7/8] Escribiendo data.json...")
    OUTPUT_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  OK {OUTPUT_JSON}")

    print("\n[8/8] Enviando email...")
    send_email(
        load_recipients(),
        data.get("summary",{}).get("key_signal",""),
        len(opps), len(projects)
    )

    print(f"\n{'='*55}\n  Completado\n{'='*55}\n")
