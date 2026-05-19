"""
Full load Bronze (target: Supabase Postgres schema 'bronze').

Trae toda la data historica desde Redshift. Usar solo cuando se quiera
reset completo (ej. watermark corrupto). Lento.

Correr:
    python -m pipelines.bronze.full_load
"""
from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pipelines._common import (  # noqa: E402
    get_engine, log_path, mandant_code, open_redshift,
    page_size, load_tables_config,
)


LOG_FILE = log_path("full_load")
MNDT = mandant_code()
PAGE = page_size()


def log(msg: str):
    print(msg, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now().isoformat()}  {msg}\n")


def ensure_control_table(engine):
    with engine.begin() as conn:
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


def log_extraction(engine, table_name, mode, rows, watermark, duration,
                   status, error=None):
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO bronze.ctrl_extraction_log
            (run_datm, table_name, mode, rows_loaded, watermark_to,
             duration_sec, status, error_detail)
            VALUES (NOW(), :tn, :m, :r, :wm, :d, :s, :e)
        """), {"tn": table_name, "m": mode, "r": rows, "wm": watermark,
               "d": duration, "s": status, "e": error})


def pull_table(rs_conn, engine, tbl_cfg: dict):
    source = tbl_cfg["source"]
    target = tbl_cfg["target"]
    order_by = tbl_cfg["order_by"]
    filter_mandant = tbl_cfg.get("filter_mandant", True)

    where = f"WHERE mndt_code = {MNDT}" if filter_mandant else ""
    started = time.time()
    log(f"\n>> {source} -> {target}")

    try:
        n_total = pd.read_sql(
            f"SELECT COUNT(*) AS n FROM {source} {where}", rs_conn
        ).iloc[0]["n"]
        log(f"   total filas: {n_total:,}")

        if n_total == 0:
            df = pd.read_sql(f"SELECT * FROM {source} {where} LIMIT 0", rs_conn)
            df["_loaded_at"] = pd.Series(dtype="datetime64[ns]")
            df["_source_table"] = pd.Series(dtype="object")
            with engine.begin() as conn:
                conn.execute(text(f'DROP TABLE IF EXISTS bronze."{target}"'))
            df.to_sql(target, engine, schema="bronze",
                      if_exists="replace", index=False)
            log_extraction(engine, target, "FULL", 0, None,
                           time.time() - started, "EMPTY")
            log("   tabla creada vacia")
            return

        offset = 0
        first = True
        while offset < n_total:
            sql = (
                f"SELECT * FROM {source} {where} "
                f"ORDER BY {order_by} LIMIT {PAGE} OFFSET {offset}"
            )
            df = pd.read_sql(sql, rs_conn)
            df["_loaded_at"] = datetime.now()
            df["_source_table"] = source

            if first:
                # primera pagina: drop + create con schema del df
                with engine.begin() as conn:
                    conn.execute(text(f'DROP TABLE IF EXISTS bronze."{target}"'))
                df.to_sql(target, engine, schema="bronze",
                          if_exists="replace", index=False,
                          method="multi", chunksize=2000)
            else:
                df.to_sql(target, engine, schema="bronze",
                          if_exists="append", index=False,
                          method="multi", chunksize=2000)
            first = False

            offset += PAGE
            log(f"   {min(offset, n_total):>10,} / {n_total:,}")

        elapsed = time.time() - started
        log_extraction(engine, target, "FULL", int(n_total),
                       datetime.now().isoformat(), elapsed, "SUCCESS")
        log(f"   OK ({elapsed:.1f}s)")

    except Exception as e:
        elapsed = time.time() - started
        log_extraction(engine, target, "FULL", 0, None, elapsed,
                       "FAILED", str(e)[:500])
        log(f"   FAIL: {e}")


def main():
    log("=" * 70)
    log("  FULL LOAD BRONZE -> Supabase Postgres")
    log("=" * 70)
    log(f"  mandant: {MNDT}")
    log(f"  page:    {PAGE:,} filas")

    engine = get_engine("bronze")
    ensure_control_table(engine)

    tables = load_tables_config()
    log(f"  tablas:  {len(tables)}")

    started_total = time.time()
    with open_redshift() as rs_conn:
        for tbl in tables:
            pull_table(rs_conn, engine, tbl)

    log("\n" + "=" * 70)
    log(f"  FULL LOAD COMPLETO en {time.time() - started_total:.1f}s")
    log("=" * 70)


if __name__ == "__main__":
    main()
