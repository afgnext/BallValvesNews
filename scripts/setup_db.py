#!/usr/bin/env python3
"""
AFG · Setup DB — Ejecutar UNA SOLA VEZ para crear el esquema en Neon.

Uso:
  export NEON_DATABASE_URL="postgresql://user:pass@host/db?sslmode=require"
  python scripts/setup_db.py
"""
import os, psycopg2

DATABASE_URL = os.environ.get("NEON_DATABASE_URL") or input("NEON_DATABASE_URL: ").strip()

SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
    id           SERIAL       PRIMARY KEY,
    report_date  DATE         NOT NULL UNIQUE,
    raw_data     JSONB        NOT NULL,
    html_content TEXT         NOT NULL,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_reports_date ON reports (report_date DESC);

-- Función para actualizar updated_at automáticamente
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_reports_updated_at ON reports;
CREATE TRIGGER trg_reports_updated_at
    BEFORE UPDATE ON reports
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
"""

print("Conectando a Neon...")
conn = psycopg2.connect(DATABASE_URL)
cur  = conn.cursor()
cur.execute(SCHEMA)
conn.commit()
cur.close()
conn.close()

print("✅ Esquema creado:")
print("   Tabla:   reports")
print("   Campos:  id, report_date, raw_data (JSONB), html_content, created_at, updated_at")
print("   Índice:  report_date DESC")
print("\nYa puedes ejecutar generate_report.py o esperar al cron de GitHub Actions.")
