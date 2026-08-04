"""
Inspeccion del estado de Bronze.
- Lista tablas y conteos
- Muestra historial de extraccion
- Sample de filas

Tambien soporta --test-connection para validar la conexion remota a Redshift.

Correr:
    python -m pipelines.bronze.inspect
    python -m pipelines.bronze.inspect --test-connection
    python -m pipelines.bronze.inspect --table rent_shop_rs_fct_reservations
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pipelines._common import (  # noqa: E402
    get_engine, open_redshift, mandant_code,
)
from sqlalchemy import text  # noqa: E402


def cmd_test_connection():
    print("=" * 70)
    print("  TEST CONEXION REDSHIFT")
    print("=" * 70)
    try:
        with open_redshift() as conn:
            ver = pd.read_sql("SELECT version() AS v", conn).iloc[0]["v"]
            print(f"  [OK] Redshift conectado")
            print(f"  version: {ver[:80]}")

            user_db = pd.read_sql("SELECT current_user, current_database()", conn).iloc[0]
            print(f"  user={user_db.iloc[0]} db={user_db.iloc[1]}")

            tables = pd.read_sql("""
                SELECT table_schema, table_name
                FROM information_schema.tables
                WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
                  AND table_schema NOT LIKE 'pg_%'
                ORDER BY 1, 2
            """, conn)
            print(f"  tablas accesibles: {len(tables)}")
            for s in tables["table_schema"].unique():
                ts = tables[tables["table_schema"] == s]
                print(f"    [{s}]")
                for t in ts["table_name"]:
                    print(f"      {t}")
    except Exception as e:
        print(f"  [X] FAIL: {type(e).__name__}: {e}")
        sys.exit(1)


def cmd_inspect_local(table: str | None = None):
    """Inspecciona bronze en Supabase Postgres (antes era SQLite local).

    Lista tablas con conteos, log de extraccion, y opcionalmente un sample.
    """
    print("=" * 70)
    print("  INSPECCION BRONZE (Supabase Postgres)")
    print("=" * 70)

    engine = get_engine("bronze")

    with engine.connect() as conn:
        conn.execute(text("SET search_path TO bronze, public"))

        # Lista de tablas en schema bronze
        tbls = conn.execute(text("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'bronze'
              AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """)).fetchall()

        print(f"\n  [{len(tbls)} tablas en schema bronze]\n")
        for (tname,) in tbls:
            try:
                n = conn.execute(text(f"SELECT COUNT(*) FROM bronze.{tname}")).scalar()
                print(f"    {tname:60} {n:>14,} filas")
            except Exception as e:
                print(f"    {tname:60} ERROR: {e}")

        # Log de extraccion
        print("\n  [Ultimas 10 corridas]")
        try:
            log_df = pd.read_sql_query(text("""
                SELECT run_datm, table_name, mode, rows_loaded, status,
                       ROUND(duration_sec::numeric, 1) AS sec
                FROM bronze.ctrl_extraction_log
                ORDER BY id DESC LIMIT 10
            """), conn)
            print(log_df.to_string(index=False))
        except Exception as e:
            print(f"  (sin tabla ctrl_extraction_log: {e})")

        # Sample de tabla especifica
        if table:
            print(f"\n  [Sample 5 filas de {table}]")
            try:
                sample = pd.read_sql_query(
                    text(f"SELECT * FROM bronze.{table} LIMIT 5"), conn
                )
                print(sample.to_string())
            except Exception as e:
                print(f"  ERROR: {e}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--test-connection", action="store_true",
                   help="Solo testea la conexion a Redshift, no toca bronze.db")
    p.add_argument("--table", default=None,
                   help="Mostrar sample de una tabla especifica")
    args = p.parse_args()

    if args.test_connection:
        cmd_test_connection()
    else:
        cmd_inspect_local(args.table)


if __name__ == "__main__":
    main()
