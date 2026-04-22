#!/usr/bin/env python3
"""
AFG Market Intelligence — Daily Report Generator
─────────────────────────────────────────────────
Orquesta búsquedas web (Tavily) + análisis (Claude API) +
almacenamiento (Neon) + generación de HTML para Vercel.

Ejecución: python scripts/generate_report.py
Requiere variables de entorno:
  ANTHROPIC_API_KEY   → console.anthropic.com
  TAVILY_API_KEY      → app.tavily.com  (free: 1000 búsquedas/mes)
  NEON_DATABASE_URL   → console.neon.tech
"""

import os, json, sys, requests, psycopg2
from psycopg2.extras import Json
from datetime import date
from pathlib import Path
import anthropic

# ── Config ─────────────────────────────────────────────────────────────────────
TODAY            = date.today()
ANTHROPIC_KEY    = os.environ["ANTHROPIC_API_KEY"]
TAVILY_KEY       = os.environ["TAVILY_API_KEY"]
DATABASE_URL     = os.environ["NEON_DATABASE_URL"]
MODEL            = "claude-sonnet-4-6"
OUTPUT_HTML      = Path(__file__).parent.parent / "public" / "index.html"

SEARCH_QUERIES = [
    f"ball valve failure oil gas refinery USA {TODAY.year}",
    f"LNG project USA valves procurement contract {TODAY.year}",
    f"tariffs steel China USA valves {TODAY.year}",
    f"stainless steel supply chain shortage USA industrial {TODAY.year}",
    f"EPC oil gas project USA refinery expansion {TODAY.year}",
    f"nearshoring valve manufacturing Mexico USA {TODAY.year}",
    f"CBAM steel carbon border adjustment {TODAY.year}",
    "pipeline valve replacement maintenance USA midstream",
    "valve supply shortage USA oil gas",
    f"Section 232 steel tariff valve industry {TODAY.year}",
]

# ── Step 1 · Web Search ────────────────────────────────────────────────────────
def tavily_search(query: str, n: int = 5) -> list[dict]:
    try:
        r = requests.post(
            "https://api.tavily.com/search",
            json={"api_key": TAVILY_KEY, "query": query,
                  "search_depth": "basic", "max_results": n,
                  "include_raw_content": False},
            timeout=20,
        )
        r.raise_for_status()
        return r.json().get("results", [])
    except Exception as e:
        print(f"  ⚠ Search failed: {query[:50]}… → {e}")
        return []

def run_searches() -> list[dict]:
    seen, results = set(), []
    for q in SEARCH_QUERIES:
        print(f"  🔍 {q}")
        for item in tavily_search(q):
            url = item.get("url", "")
            if url and url not in seen:
                seen.add(url)
                results.append(item)
    print(f"  ✅ {len(results)} fuentes únicas recopiladas")
    return results

# ── Step 2 · Análisis con Claude ───────────────────────────────────────────────
SYSTEM_PROMPT = """Eres un analista senior de inteligencia de mercado especializado en
oil & gas, supply chain industrial y comercio internacional. Tu cliente es AFG
(Alcorta Forging Group), fabricante vasco de bolas de acero inoxidable (~4",
~10 kg) para válvulas de bola, con foco en el mercado USA de oil & gas.
Devuelve ÚNICAMENTE JSON válido, sin texto adicional, sin markdown."""

USER_PROMPT = """Fecha: {today}

Analiza los siguientes resultados de búsqueda web y extrae inteligencia de
mercado accionable para vender bolas de acero inox en USA (oil & gas).

RESULTADOS DE BÚSQUEDA:
{context}

Devuelve EXACTAMENTE este JSON (sin campos extra, sin texto fuera del JSON):

{{
  "summary": {{
    "key_signal": "<señal más importante del día en 1 frase directa>",
    "market_temp": <entero 0-100 que indica calor del mercado>
  }},
  "opportunities": [
    {{
      "title": "<título concreto>",
      "company": "<empresa o proyecto>",
      "location": "<ciudad, estado>",
      "type": "<nuevo_proyecto|fallo|regulacion|supply_chain|demanda>",
      "description": "<2-3 frases con hechos reales de los resultados>",
      "probability": "<Alta|Media|Baja>",
      "tags": ["<tag1>","<tag2>"],
      "source_url": "<URL>",
      "source_title": "<título fuente>",
      "date": "<fecha si disponible, si no cadena vacía>"
    }}
  ],
  "alerts": [
    {{
      "level": "<Critica|Alta|Media>",
      "title": "<título alerta>",
      "body": "<2-3 frases concretas>",
      "source_url": "<URL>",
      "source_title": "<título>"
    }}
  ],
  "projects": [
    {{
      "name": "<nombre proyecto>",
      "phase": "<planificacion|ejecucion|operativo>",
      "companies": "<empresas involucradas>",
      "location": "<ubicación>",
      "description": "<1-2 frases>",
      "capex": "<presupuesto o cadena vacía>",
      "source_url": "<URL>"
    }}
  ],
  "risks": [
    {{
      "title": "<riesgo>",
      "impact": "<Alto|Medio|Bajo>",
      "description": "<descripción concreta>",
      "mitigation": "<acción de mitigación>"
    }}
  ],
  "actions": [
    {{
      "target": "<empresa objetivo>",
      "type": "<urgente|distribucion|partnership|comunicacion>",
      "description": "<acción concreta>",
      "signals": ["<señal1>","<señal2>"],
      "url": "<URL empresa o cadena vacía>"
    }}
  ]
}}

Requisitos: mínimo 4 oportunidades, 3 alertas, 3 proyectos, 3 riesgos, 4 acciones.
Solo incluye hallazgos respaldados por los resultados de búsqueda. Sé específico."""

def analyze(search_results: list[dict]) -> dict:
    context = "\n\n---\n\n".join(
        f"TÍTULO: {r.get('title','')}\n"
        f"URL: {r.get('url','')}\n"
        f"FECHA: {r.get('published_date','N/A')}\n"
        f"CONTENIDO: {r.get('content','')[:700]}"
        for r in search_results[:40]
    )
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    msg = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": USER_PROMPT.format(
            today=TODAY.strftime("%d %B %Y"),
            context=context,
        )}],
    )
    raw = msg.content[0].text.strip()
    # Strip markdown fences if model adds them
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.rsplit("```", 1)[0]
    return json.loads(raw.strip())

# ── Step 3 · Neon ──────────────────────────────────────────────────────────────
def store_in_neon(data: dict, html: str):
    conn = psycopg2.connect(DATABASE_URL)
    cur  = conn.cursor()
    cur.execute("""
        INSERT INTO reports (report_date, raw_data, html_content)
        VALUES (%s, %s, %s)
        ON CONFLICT (report_date)
        DO UPDATE SET
            raw_data     = EXCLUDED.raw_data,
            html_content = EXCLUDED.html_content,
            updated_at   = NOW()
    """, (TODAY, Json(data), html))
    conn.commit()
    cur.close(); conn.close()
    print("  ✅ Guardado en Neon")

# ── Step 4 · Generar HTML ──────────────────────────────────────────────────────
def _prob_tag(p):
    cfg = {"Alta": ("tag-alta","🔴"), "Media": ("tag-media","🟡"), "Baja": ("tag-baja","🟢")}
    cls, emoji = cfg.get(p, ("tag-media","🟡"))
    return f'<span class="card-tag {cls}">{emoji} {p}</span>'

def _alert_cfg(level):
    return {
        "Critica": ("var(--red)",    "level-critica", "🚨"),
        "Alta":    ("var(--orange)", "level-alta",    "⚡"),
        "Media":   ("var(--accent2)","level-media",   "🌐"),
    }.get(level, ("var(--orange)", "level-alta", "⚠️"))

def _phase_cfg(phase):
    return {
        "planificacion": ("dot-planning",  "phase-planning",  "Planificación"),
        "ejecucion":     ("dot-execution", "phase-execution", "En Ejecución"),
        "operativo":     ("dot-active",    "phase-active",    "Operativo"),
    }.get(phase, ("dot-planning", "phase-planning", phase.title()))

def _link(url, label, max_len=55):
    if not url: return ""
    label = (label or url)[:max_len]
    return f'<a class="card-link" href="{url}" target="_blank">→ {label}</a>'

def generate_html(data: dict, search_results: list[dict]) -> str:
    s        = data.get("summary", {})
    opps     = data.get("opportunities", [])
    alerts   = data.get("alerts", [])
    projects = data.get("projects", [])
    risks    = data.get("risks", [])
    actions  = data.get("actions", [])

    today_str = TODAY.strftime("%d %B %Y")
    high   = sum(1 for o in opps if o.get("probability") == "Alta")
    medium = sum(1 for o in opps if o.get("probability") == "Media")
    temp   = s.get("market_temp", 70)
    temp_color = "#4ade80" if temp < 40 else "#fbbf24" if temp < 70 else "#ff6b6b"

    # ── Oportunidades ──
    opp_html = ""
    for o in opps:
        prob  = o.get("probability", "Media")
        tags  = "".join(f'<span class="meta-chip">{t}</span>' for t in o.get("tags", []))
        opp_html += f"""
        <div class="card" data-tags="{prob.lower()} {o.get('type','')}">
          <div class="card-top">
            {_prob_tag(prob)}
            <span style="font-size:11px;color:var(--text-dim)">{o.get('date','2026')}</span>
          </div>
          <div class="card-title">{o.get('title','')}</div>
          <div class="card-company">🏢 {o.get('company','')}</div>
          <div class="card-body">{o.get('description','')}</div>
          <div class="card-meta">
            <span class="meta-chip">🗺️ {o.get('location','USA')}</span>
            {tags}
          </div>
          {_link(o.get('source_url'), o.get('source_title'))}
        </div>"""

    # ── Alertas ──
    alert_html = ""
    for a in alerts:
        color, badge_cls, icon = _alert_cfg(a.get("level","Alta"))
        alert_html += f"""
        <div class="alert-item" style="border-left:4px solid {color}">
          <div class="alert-icon">{icon}</div>
          <div style="flex:1">
            <div class="alert-level {badge_cls}">{a.get('level','Alta').upper()}</div>
            <div class="alert-title">{a.get('title','')}</div>
            <div class="alert-body">{a.get('body','')}</div>
            <div class="alert-source">{_link(a.get('source_url'), a.get('source_title'))}</div>
          </div>
        </div>"""

    # ── Proyectos ──
    proj_emoji = {"planificacion":"📋","ejecucion":"⚙️","operativo":"🔥"}
    proj_html  = ""
    for p in projects:
        dot, badge, label = _phase_cfg(p.get("phase","planificacion"))
        emoji = proj_emoji.get(p.get("phase",""), "🏗️")
        capex = f'<span class="meta-chip">💰 {p["capex"]}</span>' if p.get("capex") else ""
        proj_html += f"""
        <div class="timeline-item">
          <div class="timeline-dot {dot}">{emoji}</div>
          <div class="timeline-content">
            <div class="timeline-header">
              <div class="timeline-title">{p.get('name','')}</div>
              <span class="phase-badge {badge}">{label}</span>
            </div>
            <div class="timeline-companies">🏢 <strong>{p.get('companies','')}</strong></div>
            <div class="timeline-desc">{p.get('description','')}</div>
            <div class="timeline-tags">
              <span class="meta-chip">🗺️ {p.get('location','USA')}</span>
              {capex}
            </div>
            {_link(p.get('source_url'), 'Ver proyecto')}
          </div>
        </div>"""

    # ── Riesgos ──
    risk_pct   = {"Alto":"80%","Medio":"55%","Bajo":"30%"}
    risk_color = {"Alto":"var(--red)","Medio":"var(--orange)","Bajo":"var(--green)"}
    risk_html  = ""
    for r in risks:
        imp = r.get("impact","Medio")
        risk_html += f"""
        <div class="risk-card">
          <div class="risk-header"><span class="risk-emoji">⚠️</span>
            <div class="risk-title">{r.get('title','')}</div></div>
          <div class="risk-level-bar">
            <div class="risk-level-fill" style="width:{risk_pct.get(imp,'55%')};background:{risk_color.get(imp,'var(--orange)')}"></div>
          </div>
          <div class="risk-body">{r.get('description','')}</div>
          <div style="margin-top:10px;font-size:12px;color:var(--text-muted)">
            <strong style="color:var(--accent)">Mitigación:</strong> {r.get('mitigation','')}
          </div>
        </div>"""

    # ── Acciones ──
    atype_map = {
        "urgente":      ("urgent","🚨 URGENTE"),
        "distribucion": ("",      "📦 DISTRIBUCIÓN"),
        "partnership":  ("partner","🤝 PARTNERSHIP"),
        "comunicacion": ("partner","📣 COMUNICACIÓN"),
    }
    action_html = ""
    for a in actions:
        cls, lbl = atype_map.get(a.get("type","urgente"), ("",""))
        signals  = "".join(f'<span class="signal">{s}</span>' for s in a.get("signals",[]))
        action_html += f"""
        <div class="action-card {cls}">
          <div class="action-target">{a.get('target','')}</div>
          <div class="action-type">{lbl}</div>
          <div class="action-body">{a.get('description','')}</div>
          <div class="action-signals">{signals}</div>
          <div style="margin-top:14px">{_link(a.get('url'), 'Visitar →')}</div>
        </div>"""

    # ── Fuentes ──
    seen_src, src_links = set(), []
    for r in search_results[:12]:
        url = r.get("url","")
        if url and url not in seen_src:
            seen_src.add(url)
            title = (r.get("title","") or url)[:55]
            src_links.append(f'<a class="card-link" href="{url}" target="_blank" style="margin:3px">→ {title}</a>')

    # ── CSS (inline, igual que el reporte manual) ──
    CSS = """
    :root{--bg:#0d1117;--surface:#161b22;--surface2:#1c2230;--border:#21262d;
      --accent:#e8a225;--accent2:#1f6feb;--green:#238636;--red:#da3633;
      --orange:#d29922;--purple:#8b5cf6;--text:#e6edf3;--text-muted:#7d8590;--text-dim:#484f58}
    *{margin:0;padding:0;box-sizing:border-box}
    body{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;font-size:14px;line-height:1.6}
    header{background:linear-gradient(135deg,#0d1117 0%,#161b22 50%,#1a1f2e 100%);border-bottom:1px solid var(--border);padding:24px 32px 0;position:sticky;top:0;z-index:100}
    .header-top{display:flex;align-items:center;justify-content:space-between;margin-bottom:16px}
    .logo{display:flex;align-items:center;gap:12px}
    .logo-badge{background:var(--accent);color:#000;font-weight:800;font-size:13px;padding:5px 10px;border-radius:6px;letter-spacing:.5px}
    .logo-title{font-size:17px;font-weight:600}.logo-sub{font-size:12px;color:var(--text-muted)}
    .date-badge{display:flex;align-items:center;gap:8px;background:var(--surface2);border:1px solid var(--border);padding:6px 14px;border-radius:20px;font-size:12px;color:var(--text-muted)}
    .dot{width:7px;height:7px;background:var(--green);border-radius:50%;animation:pulse 2s infinite}
    @keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
    .nav-tabs{display:flex;gap:4px;overflow-x:auto}
    .nav-tab{padding:10px 16px;border:none;background:transparent;color:var(--text-muted);cursor:pointer;font-size:13px;font-weight:500;border-bottom:2px solid transparent;transition:all .2s;white-space:nowrap;display:flex;align-items:center;gap:6px}
    .nav-tab:hover{color:var(--text)}.nav-tab.active{color:var(--accent);border-bottom-color:var(--accent)}
    .nav-tab .badge{background:var(--surface2);border:1px solid var(--border);border-radius:10px;padding:1px 7px;font-size:11px;color:var(--text-muted)}
    .nav-tab.active .badge{background:var(--accent);color:#000;border-color:var(--accent)}
    main{padding:28px 32px;max-width:1400px;margin:0 auto}
    .section{display:none}.section.active{display:block}
    .section-header{display:flex;align-items:center;gap:12px;margin-bottom:24px}
    .section-icon{font-size:22px}.section-title{font-size:20px;font-weight:700}
    .section-desc{font-size:13px;color:var(--text-muted);margin-top:2px}
    .kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;margin-bottom:32px}
    .kpi-card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:20px;position:relative;overflow:hidden}
    .kpi-card::before{content:'';position:absolute;top:0;left:0;width:100%;height:3px}
    .kpi-card.alta::before{background:var(--red)}.kpi-card.media::before{background:var(--orange)}
    .kpi-card.verde::before{background:var(--green)}.kpi-card.azul::before{background:var(--accent2)}
    .kpi-card.purple::before{background:var(--purple)}
    .kpi-number{font-size:32px;font-weight:800;margin-bottom:4px}
    .kpi-card.alta .kpi-number{color:var(--red)}.kpi-card.media .kpi-number{color:var(--orange)}
    .kpi-card.verde .kpi-number{color:var(--green)}.kpi-card.azul .kpi-number{color:var(--accent2)}
    .kpi-card.purple .kpi-number{color:var(--purple)}
    .kpi-label{font-size:12px;color:var(--text-muted);font-weight:500;text-transform:uppercase;letter-spacing:.5px}
    .kpi-sub{font-size:11px;color:var(--text-dim);margin-top:4px}
    .card-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:16px}
    .card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:20px;transition:border-color .2s,transform .15s}
    .card:hover{border-color:#3d4451;transform:translateY(-2px)}
    .card-top{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px}
    .card-tag{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;padding:3px 8px;border-radius:4px}
    .tag-alta{background:rgba(218,54,51,.15);color:#ff6b6b;border:1px solid rgba(218,54,51,.3)}
    .tag-media{background:rgba(210,153,34,.15);color:#fbbf24;border:1px solid rgba(210,153,34,.3)}
    .tag-baja{background:rgba(35,134,54,.15);color:#4ade80;border:1px solid rgba(35,134,54,.3)}
    .card-title{font-size:15px;font-weight:700;margin-bottom:6px;line-height:1.4}
    .card-company{font-size:12px;color:var(--accent2);font-weight:600;margin-bottom:10px}
    .card-body{font-size:13px;color:var(--text-muted);line-height:1.6}
    .card-meta{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px;padding-top:14px;border-top:1px solid var(--border)}
    .meta-chip{font-size:11px;padding:3px 9px;border-radius:20px;background:var(--surface2);border:1px solid var(--border);color:var(--text-muted)}
    .card-link{display:inline-flex;align-items:center;gap:5px;font-size:12px;color:var(--accent2);text-decoration:none;font-weight:500;margin-top:10px;padding:5px 10px;background:rgba(31,111,235,.1);border:1px solid rgba(31,111,235,.2);border-radius:6px;transition:background .2s}
    .card-link:hover{background:rgba(31,111,235,.2)}
    .timeline{position:relative}
    .timeline::before{content:'';position:absolute;left:20px;top:0;bottom:0;width:2px;background:var(--border)}
    .timeline-item{display:flex;gap:24px;margin-bottom:24px;position:relative}
    .timeline-dot{width:40px;height:40px;border-radius:50%;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:16px;position:relative;z-index:1}
    .dot-active{background:rgba(35,134,54,.2);border:2px solid var(--green)}
    .dot-planning{background:rgba(31,111,235,.2);border:2px solid var(--accent2)}
    .dot-execution{background:rgba(232,162,37,.2);border:2px solid var(--accent)}
    .timeline-content{flex:1;background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:18px}
    .timeline-header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px}
    .timeline-title{font-size:15px;font-weight:700}
    .phase-badge{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;padding:3px 9px;border-radius:12px}
    .phase-active{background:rgba(35,134,54,.2);color:#4ade80}
    .phase-planning{background:rgba(31,111,235,.2);color:#60a5fa}
    .phase-execution{background:rgba(232,162,37,.2);color:#fbbf24}
    .timeline-companies{font-size:12px;color:var(--text-muted);margin-bottom:8px}
    .timeline-desc{font-size:13px;color:var(--text-muted)}
    .timeline-tags{display:flex;flex-wrap:wrap;gap:6px;margin-top:12px}
    .alert-list{display:flex;flex-direction:column;gap:12px}
    .alert-item{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:16px 20px;display:flex;gap:14px;align-items:flex-start}
    .alert-icon{font-size:20px;flex-shrink:0;margin-top:2px}
    .alert-level{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;padding:2px 8px;border-radius:4px;margin-bottom:6px;display:inline-block}
    .level-critica{background:rgba(218,54,51,.2);color:#ff6b6b}
    .level-alta{background:rgba(210,153,34,.2);color:#fbbf24}
    .level-media{background:rgba(31,111,235,.2);color:#60a5fa}
    .alert-title{font-size:14px;font-weight:700;margin-bottom:6px}
    .alert-body{font-size:13px;color:var(--text-muted)}.alert-source{margin-top:8px}
    .action-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px}
    .action-card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:20px;border-left:4px solid var(--accent)}
    .action-card.urgent{border-left-color:var(--red)}.action-card.partner{border-left-color:var(--purple)}
    .action-target{font-size:16px;font-weight:700;margin-bottom:4px}
    .action-type{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.5px;color:var(--accent);margin-bottom:12px}
    .action-card.urgent .action-type{color:#ff6b6b}.action-card.partner .action-type{color:#c4b5fd}
    .action-body{font-size:13px;color:var(--text-muted);margin-bottom:14px}
    .action-signals{display:flex;flex-direction:column;gap:5px}
    .signal{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--text-muted)}
    .signal::before{content:'→';color:var(--accent);font-weight:700}
    .action-card.urgent .signal::before{color:#ff6b6b}.action-card.partner .signal::before{color:#c4b5fd}
    .risk-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
    @media(max-width:700px){.risk-grid{grid-template-columns:1fr}}
    .risk-card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:20px}
    .risk-header{display:flex;align-items:center;gap:10px;margin-bottom:12px}
    .risk-emoji{font-size:20px}.risk-title{font-size:14px;font-weight:700}
    .risk-level-bar{height:6px;background:var(--surface2);border-radius:3px;margin-bottom:12px}
    .risk-level-fill{height:6px;border-radius:3px}
    .risk-body{font-size:13px;color:var(--text-muted)}
    .filter-bar{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:20px}
    .filter-chip{padding:6px 14px;border-radius:20px;background:var(--surface2);border:1px solid var(--border);color:var(--text-muted);font-size:12px;cursor:pointer;transition:all .2s}
    .filter-chip:hover{color:var(--text)}.filter-chip.active{background:rgba(232,162,37,.15);color:var(--accent);border-color:var(--accent)}
    footer{border-top:1px solid var(--border);margin:40px 32px 0;padding:20px 0;text-align:center;font-size:12px;color:var(--text-dim)}
    @media(max-width:768px){header,main{padding-left:16px;padding-right:16px}.card-grid{grid-template-columns:1fr}.kpi-grid{grid-template-columns:1fr 1fr}}
    """

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <title>AFG · Market Intelligence · {today_str}</title>
  <style>{CSS}</style>
</head>
<body>
<header>
  <div class="header-top">
    <div class="logo">
      <div class="logo-badge">AFG</div>
      <div>
        <div class="logo-title">Market Intelligence · Ball Valves</div>
        <div class="logo-sub">Stainless Steel Balls (~4" / ~10 kg) — Oil &amp; Gas USA</div>
      </div>
    </div>
    <div class="date-badge"><span class="dot"></span>Actualizado: {today_str}</div>
  </div>
  <div class="nav-tabs">
    <button class="nav-tab active" onclick="show('dashboard',this)">📊 Dashboard</button>
    <button class="nav-tab" onclick="show('oportunidades',this)">🔎 Oportunidades <span class="badge">{len(opps)}</span></button>
    <button class="nav-tab" onclick="show('alertas',this)">⚠️ Alertas <span class="badge">{len(alerts)}</span></button>
    <button class="nav-tab" onclick="show('proyectos',this)">🏭 Proyectos <span class="badge">{len(projects)}</span></button>
    <button class="nav-tab" onclick="show('riesgos',this)">📉 Riesgos <span class="badge">{len(risks)}</span></button>
    <button class="nav-tab" onclick="show('acciones',this)">🎯 Acciones <span class="badge">{len(actions)}</span></button>
  </div>
</header>
<main>

<!-- DASHBOARD -->
<section id="dashboard" class="section active">
  <div class="section-header">
    <span class="section-icon">📊</span>
    <div><div class="section-title">Executive Dashboard</div>
    <div class="section-desc">Resumen ejecutivo · {today_str}</div></div>
  </div>
  <div class="kpi-grid">
    <div class="kpi-card alta"><div class="kpi-number">{high}</div><div class="kpi-label">Oportunidades Altas</div><div class="kpi-sub">Urgencia detectada</div></div>
    <div class="kpi-card media"><div class="kpi-number">{medium}</div><div class="kpi-label">Oportunidades Medias</div><div class="kpi-sub">Potencial a desarrollar</div></div>
    <div class="kpi-card azul"><div class="kpi-number">{len(projects)}</div><div class="kpi-label">Proyectos Activos</div><div class="kpi-sub">EPC / LNG / Midstream</div></div>
    <div class="kpi-card verde"><div class="kpi-number">{len(alerts)}</div><div class="kpi-label">Alertas de Mercado</div><div class="kpi-sub">Supply chain + regulación</div></div>
    <div class="kpi-card purple"><div class="kpi-number" style="color:var(--purple)">{temp}</div><div class="kpi-label">Temperatura Mercado</div><div class="kpi-sub">Índice 0–100</div></div>
  </div>
  <div style="background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:20px;margin-bottom:24px;border-left:4px solid {temp_color}">
    <div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;color:var(--text-muted);margin-bottom:8px">🔑 Señal Clave del Día</div>
    <div style="font-size:16px;font-weight:700">{s.get('key_signal','Análisis completado')}</div>
  </div>
  <div style="background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:20px">
    <div style="font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;color:var(--text-muted);margin-bottom:12px">📰 Fuentes Consultadas ({len(search_results)})</div>
    <div style="display:flex;flex-wrap:wrap;gap:6px">{''.join(src_links)}</div>
  </div>
</section>

<!-- OPORTUNIDADES -->
<section id="oportunidades" class="section">
  <div class="section-header">
    <span class="section-icon">🔎</span>
    <div><div class="section-title">Oportunidades Detectadas</div>
    <div class="section-desc">Señales de demanda de bolas de acero inoxidable para válvulas — USA Oil &amp; Gas</div></div>
  </div>
  <div class="filter-bar">
    <div class="filter-chip active" onclick="filterCards(this,'all')">Todas ({len(opps)})</div>
    <div class="filter-chip" onclick="filterCards(this,'alta')">🔴 Alta probabilidad</div>
    <div class="filter-chip" onclick="filterCards(this,'media')">🟡 Media probabilidad</div>
  </div>
  <div class="card-grid" id="opp-grid">{opp_html}</div>
</section>

<!-- ALERTAS -->
<section id="alertas" class="section">
  <div class="section-header">
    <span class="section-icon">⚠️</span>
    <div><div class="section-title">Alertas de Mercado</div>
    <div class="section-desc">Cambios críticos en supply chain, regulación y comercio internacional</div></div>
  </div>
  <div class="alert-list">{alert_html}</div>
</section>

<!-- PROYECTOS -->
<section id="proyectos" class="section">
  <div class="section-header">
    <span class="section-icon">🏭</span>
    <div><div class="section-title">Proyectos Relevantes</div>
    <div class="section-desc">Pipeline de proyectos EPC / LNG / Midstream con demanda de componentes</div></div>
  </div>
  <div class="timeline">{proj_html}</div>
</section>

<!-- RIESGOS -->
<section id="riesgos" class="section">
  <div class="section-header">
    <span class="section-icon">📉</span>
    <div><div class="section-title">Riesgos y Barreras</div>
    <div class="section-desc">Factores que pueden limitar el acceso de AFG al mercado USA</div></div>
  </div>
  <div class="risk-grid">{risk_html}</div>
</section>

<!-- ACCIONES -->
<section id="acciones" class="section">
  <div class="section-header">
    <span class="section-icon">🎯</span>
    <div><div class="section-title">Acciones Recomendadas</div>
    <div class="section-desc">Plan de acción prioritario basado en inteligencia del día</div></div>
  </div>
  <div class="action-grid">{action_html}</div>
</section>

</main>
<footer>
  <div>AFG Market Intelligence · Ball Valves USA · Oil &amp; Gas</div>
  <div style="margin-top:4px">Auto-generado: {today_str} · Claude {MODEL} + Tavily · Neon DB</div>
</footer>
<script>
  function show(id,tab){{
    document.querySelectorAll('.section').forEach(s=>s.classList.remove('active'));
    document.querySelectorAll('.nav-tab').forEach(t=>t.classList.remove('active'));
    document.getElementById(id).classList.add('active');
    if(tab)tab.classList.add('active');
  }}
  function filterCards(chip,tag){{
    document.querySelectorAll('.filter-chip').forEach(c=>c.classList.remove('active'));
    chip.classList.add('active');
    document.querySelectorAll('#opp-grid .card').forEach(c=>{{
      c.style.display=(tag==='all'||(c.dataset.tags||'').includes(tag))?'':'none';
    }});
  }}
</script>
</body>
</html>"""

# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"\n{'─'*60}")
    print(f"  AFG Market Intelligence Report · {TODAY}")
    print(f"{'─'*60}\n")

    print("📡 [1/5] Buscando en la web...")
    results = run_searches()

    print("\n🧠 [2/5] Analizando con Claude...")
    data = analyze(results)
    print(f"  ✅ {len(data.get('opportunities',[]))} oportunidades · "
          f"{len(data.get('alerts',[]))} alertas · "
          f"{len(data.get('projects',[]))} proyectos")

    print("\n✍️  [3/5] Generando HTML...")
    html = generate_html(data, results)

    print("\n💾 [4/5] Guardando en Neon DB...")
    store_in_neon(data, html)

    print("\n📄 [5/5] Escribiendo public/index.html...")
    OUTPUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_HTML.write_text(html, encoding="utf-8")
    print(f"  ✅ {OUTPUT_HTML}")

    print(f"\n{'─'*60}")
    print("  ✅ Reporte completado con éxito")
    print(f"{'─'*60}\n")
