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
    BRONZE_DB, open_local, open_redshift, mandant_code,
)


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
    print("=" * 70)
    print(f"  INSPECCION BRONZE LOCAL ({BRONZE_DB})")
    print("=" * 70)

    if not BRONZE_DB.exists():
        print(f"  [X] No existe {BRONZE_DB}")
        print("  -> Corre primero: python -m pipelines.bronze.full_load")
        sys.exit(1)

    print(f"  Tamano: {BRONZE_DB.stat().st_size / 1024 / 1024:.2f} MB")

    con = open_local("bronze", read_only=True)

    # Lista de tablas (sqlite_master)
    tbls = con.execute("""
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name NOT LIKE 'sqlite_%'
        ORDER BY name
    """).fetchall()

    print(f"\n  [{len(tbls)} tablas en bronze.db]\n")
    for (tname,) in tbls:
        try:
            n = con.execute(f"SELECT COUNT(*) FROM {tname}").fetchone()[0]
            print(f"    {tname:60} {n:>14,} filas")
        except Exception as e:
            print(f"    {tname:60} ERROR: {e}")

    # Log de extraccion
    print("\n  [Ultimas 10 corridas]")
    try:
        log_df = pd.read_sql_query("""
            SELECT run_datm, table_name, mode, rows_loaded, status,
                   ROUND(duration_sec, 1) AS sec
            FROM ctrl_extraction_log
            ORDER BY id DESC LIMIT 10
        """, con)
        print(log_df.to_string(index=False))
    except Exception as e:
        print(f"  (sin tabla ctrl_extraction_log: {e})")

    # Sample de tabla especifica
    if table:
        print(f"\n  [Sample 5 filas de {table}]")
        try:
            sample = pd.read_sql_query(f"SELECT * FROM {table} LIMIT 5", con)
            print(sample.to_string())
        except Exception as e:
            print(f"  ERROR: {e}")

    con.close()


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
