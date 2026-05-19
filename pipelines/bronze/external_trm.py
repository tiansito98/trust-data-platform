"""
TRM (Tasa Representativa del Mercado) USD->COP desde datos.gov.co.

Target: bronze.external_trm_diaria en Supabase Postgres.

Dataset: 32sa-8pi3 (Superintendencia Financiera, certificado Banrep).
Endpoint: https://www.datos.gov.co/resource/32sa-8pi3.json

Modos:
  - full: descarga todo desde 2024-01-01 (560 filas aprox). Borra + recarga.
  - incremental: descarga desde MAX(vigenciadesde) + 1 dia. Si la tabla
    no existe o esta vacia, hace full automaticamente.

Correr:
    python -m pipelines.bronze.external_trm                 # incremental (default)
    python -m pipelines.bronze.external_trm --full          # full reload desde 2024
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pipelines._common import get_engine, log_path  # noqa: E402

DATASET_ID = "32sa-8pi3"
BASE_URL = f"https://www.datos.gov.co/resource/{DATASET_ID}.json"
SOURCE_LABEL = f"datos.gov.co/resource/{DATASET_ID}"
HISTORY_START = "2024-01-01"
PAGE_SIZE = 1000
HTTP_TIMEOUT = 30

LOG_FILE = log_path("external_trm")


def log(msg: str):
    print(msg, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now().isoformat()}  {msg}\n")


def fetch_page(where_clause: str, offset: int) -> list[dict]:
    params = {
        "$where": where_clause,
        "$order": "vigenciadesde ASC",
        "$limit": PAGE_SIZE,
        "$offset": offset,
    }
    url = f"{BASE_URL}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT) as r:
        return json.load(r)


def fetch_all(where_clause: str) -> list[dict]:
    out: list[dict] = []
    offset = 0
    while True:
        page = fetch_page(where_clause, offset)
        out.extend(page)
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return out


def ensure_table(engine):
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS bronze.external_trm_diaria (
                vigenciadesde DATE PRIMARY KEY,
                vigenciahasta DATE NOT NULL,
                valor         NUMERIC(14,4) NOT NULL,
                unidad        TEXT NOT NULL DEFAULT 'COP',
                _loaded_at    TIMESTAMPTZ NOT NULL,
                _source       TEXT NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS bronze.ctrl_extraction_log (
                id            BIGSERIAL PRIMARY KEY,
                run_datm      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                table_name    TEXT NOT NULL,
                mode          TEXT,
                rows_loaded   BIGINT,
                watermark_to  TEXT,
                duration_sec  DOUBLE PRECISION,
                status        TEXT,
                error_detail  TEXT
            )
        """))


def upsert_rows(engine, rows: list[dict]) -> int:
    if not rows:
        return 0
    loaded_at = datetime.now()
    payload = [
        {
            "vigenciadesde": r["vigenciadesde"][:10],
            "vigenciahasta": r["vigenciahasta"][:10],
            "valor": float(r["valor"]),
            "unidad": r.get("unidad", "COP"),
            "loaded_at": loaded_at,
            "source": SOURCE_LABEL,
        }
        for r in rows
    ]
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO bronze.external_trm_diaria
                (vigenciadesde, vigenciahasta, valor, unidad, _loaded_at, _source)
            VALUES (:vigenciadesde, :vigenciahasta, :valor, :unidad,
                    :loaded_at, :source)
            ON CONFLICT (vigenciadesde) DO UPDATE SET
                vigenciahasta = EXCLUDED.vigenciahasta,
                valor         = EXCLUDED.valor,
                unidad        = EXCLUDED.unidad,
                _loaded_at    = EXCLUDED._loaded_at,
                _source       = EXCLUDED._source
        """), payload)
    return len(payload)


def latest_vigenciadesde(engine) -> str | None:
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT MAX(vigenciadesde) FROM bronze.external_trm_diaria"
        )).fetchone()
    return row[0].isoformat() if row and row[0] else None


def log_extraction(engine, mode: str, rows: int, watermark: str | None,
                   duration: float, status: str, error: str | None = None):
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO bronze.ctrl_extraction_log
                (run_datm, table_name, mode, rows_loaded, watermark_to,
                 duration_sec, status, error_detail)
            VALUES (NOW(), 'external_trm_diaria', :m, :r, :wm, :d, :s, :e)
        """), {"m": mode, "r": rows, "wm": watermark, "d": duration,
               "s": status, "e": error})


def run(mode: str = "incremental"):
    started = time.time()
    engine = get_engine("bronze")
    ensure_table(engine)

    if mode == "full":
        log(f">> external_trm (mode: FULL) -- desde {HISTORY_START}")
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM bronze.external_trm_diaria"))
        where = f"vigenciadesde >= '{HISTORY_START}'"
    else:
        last = latest_vigenciadesde(engine)
        if last is None:
            log(">> external_trm: tabla vacia, cambiando a FULL")
            return run(mode="full")
        log(f">> external_trm (mode: INCREMENTAL) -- desde > {last}")
        where = f"vigenciadesde > '{last}'"

    try:
        rows = fetch_all(where)
        n = upsert_rows(engine, rows)
        new_watermark = latest_vigenciadesde(engine)
        duration = time.time() - started
        if n == 0:
            log(f"   sin cambios ({duration:.1f}s)")
            log_extraction(engine, mode, 0, new_watermark, duration, "EMPTY")
        else:
            log(f"   {n} filas; nuevo watermark: {new_watermark} ({duration:.1f}s)")
            log_extraction(engine, mode, n, new_watermark, duration, "SUCCESS")
    except Exception as e:
        duration = time.time() - started
        log(f"   FAIL: {e}")
        log_extraction(engine, mode, 0, None, duration, "FAILED", str(e))
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true",
                        help="Forzar full load desde 2024-01-01")
    args = parser.parse_args()
    run(mode="full" if args.full else "incremental")


if __name__ == "__main__":
    main()
