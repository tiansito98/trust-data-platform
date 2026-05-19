"""
Refresh incremental Bronze (target: Supabase Postgres schema 'bronze').

Trae solo filas nuevas/modificadas desde la ultima corrida.

Modos soportados (config/tables.yml):
  - full: re-load completo (para tablas pequenas/poco volatiles)
  - incremental_watermark: usa columna timestamp para detectar cambios

Correr:
    python -m pipelines.bronze.incremental
o desde el orchestrator:
    python scripts/run_pipeline.py
"""
from __future__ import annotations

import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pipelines._common import (  # noqa: E402
    get_engine, initial_lookback_days, log_path, mandant_code,
    open_redshift, page_size, load_tables_config,
)


LOG_FILE = log_path("incremental")
MNDT = mandant_code()
PAGE = page_size()
LOOKBACK = initial_lookback_days()

# Identificadores SQL aceptables (snake_case). Defensa frente a inyeccion via YAML.
_SAFE_IDENT = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def log(msg: str):
    print(msg, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now().isoformat()}  {msg}\n")


def _safe(ident: str) -> str:
    """Valida y devuelve identifier seguro. tables.yml es trusted pero defendemos."""
    if not _SAFE_IDENT.match(ident):
        raise ValueError(f"Identifier invalido: {ident!r}")
    return ident


def ensure_control_table(engine):
    """ctrl_extraction_log se crea por setup_postgres.sql; esto es defensivo."""
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


def get_last_watermark(engine, table_name: str) -> str | None:
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT watermark_to FROM bronze.ctrl_extraction_log
            WHERE table_name = :t AND status IN ('SUCCESS','EMPTY')
              AND watermark_to IS NOT NULL
            ORDER BY id DESC LIMIT 1
        """), {"t": table_name}).fetchone()
    return row[0] if row else None


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


def _table_exists(engine, target: str) -> bool:
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'bronze' AND table_name = :t
        """), {"t": target}).fetchone()
    return row is not None


def upsert_to_bronze(engine, target: str, df: pd.DataFrame, pk_cols: list[str]):
    """
    DELETE filas con PK presente en df + INSERT con bulk via pandas.to_sql.
    Usa staging table temporaria 'stg_<target>' en schema bronze.
    """
    if df.empty:
        return

    target = _safe(target)
    for c in pk_cols:
        _safe(c)

    stg = f"stg_{target}"

    # Drop staging si quedo de corrida previa fallida
    with engine.begin() as conn:
        conn.execute(text(f'DROP TABLE IF EXISTS bronze."{stg}"'))

    # Pandas escribe la staging con el schema del df
    df.to_sql(stg, engine, schema="bronze", if_exists="replace",
              index=False, method="multi", chunksize=2000)

    try:
        with engine.begin() as conn:
            # Crea destino con schema vacio si no existe
            if not _table_exists(engine, target):
                conn.execute(text(
                    f'CREATE TABLE bronze."{target}" '
                    f'(LIKE bronze."{stg}" INCLUDING ALL)'
                ))

            # DELETE-INSERT por PK
            pk_quoted = ", ".join(f'"{c}"' for c in pk_cols)
            conn.execute(text(f'''
                DELETE FROM bronze."{target}" t
                USING bronze."{stg}" s
                WHERE {" AND ".join(f't."{c}" = s."{c}"' for c in pk_cols)}
            '''))

            # INSERT (ordenamos columnas por nombre para evitar mismatches)
            cols = [r[0] for r in conn.execute(text(
                f"SELECT column_name FROM information_schema.columns "
                f"WHERE table_schema = 'bronze' AND table_name = '{stg}' "
                f"ORDER BY ordinal_position"
            )).fetchall()]
            col_list = ", ".join(f'"{c}"' for c in cols)
            conn.execute(text(
                f'INSERT INTO bronze."{target}" ({col_list}) '
                f'SELECT {col_list} FROM bronze."{stg}"'
            ))
    finally:
        with engine.begin() as conn:
            conn.execute(text(f'DROP TABLE IF EXISTS bronze."{stg}"'))


def refresh_table(rs_conn, engine, tbl_cfg: dict):
    source = tbl_cfg["source"]
    target = tbl_cfg["target"]
    order_by = tbl_cfg["order_by"]
    mode = tbl_cfg.get("mode", "full")
    filter_mandant = tbl_cfg.get("filter_mandant", True)
    pk = tbl_cfg.get("pk", [])

    where_mandant = f"WHERE mndt_code = {MNDT}" if filter_mandant else "WHERE 1=1"
    started = time.time()
    log(f"\n>> {source} (mode: {mode})")

    new_wm = None
    n_total = 0
    try:
        if mode == "full":
            n_total = pd.read_sql(
                f"SELECT COUNT(*) AS n FROM {source} {where_mandant}", rs_conn
            ).iloc[0]["n"]
            df = pd.read_sql(
                f"SELECT * FROM {source} {where_mandant} ORDER BY {order_by}", rs_conn
            )
            df["_loaded_at"] = datetime.now()
            df["_source_table"] = source
            # full reload: drop + recrea
            with engine.begin() as conn:
                conn.execute(text(f'DROP TABLE IF EXISTS bronze."{_safe(target)}"'))
            df.to_sql(target, engine, schema="bronze",
                      if_exists="replace", index=False,
                      method="multi", chunksize=2000)
            new_wm = datetime.now().isoformat()
            log(f"   FULL reload: {n_total:,} filas")

        elif mode == "incremental_watermark":
            wm_col = tbl_cfg["watermark_col"]
            last_wm = get_last_watermark(engine, target)
            if last_wm is None:
                last_wm = (datetime.now() - timedelta(days=LOOKBACK)).isoformat()
                log(f"   primer run; usando lookback de {LOOKBACK} dias")
            log(f"   desde {wm_col} > '{last_wm}'")

            sql = (
                f"SELECT * FROM {source} {where_mandant} "
                f"AND {wm_col} > '{last_wm}' ORDER BY {wm_col}"
            )
            df = pd.read_sql(sql, rs_conn)
            n_total = len(df)

            if n_total == 0:
                log("   sin cambios")
                new_wm = last_wm
            else:
                df["_loaded_at"] = datetime.now()
                df["_source_table"] = source
                if pk:
                    upsert_to_bronze(engine, target, df, pk)
                else:
                    df.to_sql(target, engine, schema="bronze",
                              if_exists="append", index=False,
                              method="multi", chunksize=2000)
                new_wm = str(df[wm_col].max())
                log(f"   {n_total:,} filas; nuevo watermark: {new_wm}")
        else:
            raise ValueError(f"Mode desconocido: {mode}")

        elapsed = time.time() - started
        log_extraction(engine, target, mode.upper(), int(n_total), new_wm,
                       elapsed, "SUCCESS")
        log(f"   OK ({elapsed:.1f}s)")

    except Exception as e:
        elapsed = time.time() - started
        log_extraction(engine, target, mode.upper(), 0, None, elapsed,
                       "FAILED", str(e)[:500])
        log(f"   FAIL: {e}")


def main():
    log("=" * 70)
    log("  INCREMENTAL REFRESH BRONZE -> Supabase Postgres")
    log("=" * 70)

    engine = get_engine("bronze")
    ensure_control_table(engine)

    tables = load_tables_config()
    log(f"  tablas a refresh: {len(tables)}")

    started_total = time.time()
    with open_redshift() as rs_conn:
        for tbl in tables:
            refresh_table(rs_conn, engine, tbl)

    log("\n" + "=" * 70)
    log(f"  REFRESH COMPLETO en {time.time() - started_total:.1f}s")
    log("=" * 70)


if __name__ == "__main__":
    main()
