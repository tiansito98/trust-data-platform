"""
Explorador REMOTO - introspecciona el Redshift de Sixt SIN bajarlo.

Util para:
  - Confirmar nombres de columna ANTES del full load
  - Identificar columnas timestamp candidatas a watermark
  - Confirmar que tablas existen y tienen filas para mandant 409
  - Ahorrar el ciclo "full load (2h) -> error -> ajustar -> repetir"

NOTA: hace queries al Redshift, no toca DuckDB local.

Correr:
    python -m pipelines.bronze.explore_remote
    python -m pipelines.bronze.explore_remote --schema rent_shop
    python -m pipelines.bronze.explore_remote --table rs_fct_reservations
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pipelines._common import (  # noqa: E402
    ROOT, mandant_code, open_redshift, query_redshift,
)

DOCS_DIR = ROOT / "docs"
DOCS_DIR.mkdir(exist_ok=True)
OUTPUT = DOCS_DIR / "remote_schema.md"

MNDT = mandant_code()


def list_all_tables(conn) -> pd.DataFrame:
    return query_redshift(conn, """
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
          AND table_schema NOT LIKE 'pg_%'
        ORDER BY table_schema, table_name
    """)


def list_columns(conn, schema: str, table: str) -> pd.DataFrame:
    """Lee SVV_REDSHIFT_COLUMNS — soporta datashares de Data Exchange.

    information_schema.columns viene vacio para tablas datashare en Redshift consumer,
    asi que usamos la vista del catalogo SVV_REDSHIFT_COLUMNS que si las muestra.
    """
    df = query_redshift(conn, f"""
        SELECT
            ordinal_position,
            column_name,
            data_type,
            is_nullable
        FROM SVV_REDSHIFT_COLUMNS
        WHERE schema_name = '{schema}'
          AND table_name = '{table}'
        ORDER BY ordinal_position
    """)
    # max_length viene embebido en data_type (ej. 'character varying(50)', 'numeric(10,0)')
    df["max_length"] = df["data_type"].str.extract(r"\((\d+)").iloc[:, 0]
    return df


def get_row_count_for_mandant(conn, schema: str, table: str) -> int | None:
    """Retorna count, o None si la tabla no tiene mndt_code."""
    try:
        df = query_redshift(conn,
            f"SELECT COUNT(*) AS n FROM {schema}.{table} WHERE mndt_code = {MNDT}")
        return int(df.iloc[0]["n"])
    except Exception:
        # Sin mndt_code, intentar full count
        try:
            df = query_redshift(conn, f"SELECT COUNT(*) AS n FROM {schema}.{table}")
            return int(df.iloc[0]["n"])
        except Exception:
            return None


def get_timestamp_columns(cols_df: pd.DataFrame) -> list[str]:
    """Identifica columnas que son timestamp/date - candidatos a watermark."""
    is_temporal = cols_df["data_type"].str.lower().str.contains(
        "timestamp|date|time", regex=True, na=False
    )
    return cols_df[is_temporal]["column_name"].tolist()


def get_primary_key_candidates(cols_df: pd.DataFrame) -> list[str]:
    """Heuristica: columnas con sufijo _resn, _mvnr, _snr, _id, _kdnr son posibles PKs."""
    keywords = ["_resn", "_mvnr", "_snr", "_id", "_kdnr", "_int_num", "_code"]
    return [
        c for c in cols_df["column_name"]
        if any(c.lower().endswith(kw) for kw in keywords)
    ]


def render_table_md(schema: str, table: str, cols_df: pd.DataFrame, n_rows: int | None) -> list[str]:
    md = []
    md.append(f"\n## `{schema}.{table}`\n")

    if n_rows is None:
        md.append(f"**Filas para mandant {MNDT}:** N/A (sin mndt_code o error)\n")
    else:
        md.append(f"**Filas para mandant {MNDT}:** {n_rows:,}\n")

    ts_cols = get_timestamp_columns(cols_df)
    if ts_cols:
        md.append(f"**Columnas timestamp (candidatos watermark):** `{', '.join(ts_cols)}`\n")

    pk_cands = get_primary_key_candidates(cols_df)
    if pk_cands:
        md.append(f"**Posibles PK:** `{', '.join(pk_cands[:3])}`\n")

    md.append(f"\n### Columnas ({len(cols_df)})\n")
    md.append("| # | Columna | Tipo | Nullable | Max len |")
    md.append("|---|---|---|---|---|")
    for _, row in cols_df.iterrows():
        md.append(
            f"| {row['ordinal_position']} | `{row['column_name']}` | "
            f"`{row['data_type']}` | {row['is_nullable']} | "
            f"{row['max_length'] or ''} |"
        )

    return md


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--schema", default=None, help="Solo este schema (ej. rent_shop)")
    p.add_argument("--table", default=None, help="Solo esta tabla (sin schema)")
    p.add_argument("--quick", action="store_true",
                   help="Skip conteo de filas (mas rapido)")
    args = p.parse_args()

    print("=" * 70)
    print("  EXPLORE REMOTE - introspecciona Redshift de Sixt")
    print("=" * 70)
    print(f"  output: {OUTPUT}")
    print(f"  mandant: {MNDT}")
    print()

    md_sections = []
    md_sections.append("# Schema remoto - Redshift Sixt\n")
    md_sections.append(f"\n> Generado el {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
    md_sections.append(f"\n**Mandant filtrado:** `{MNDT}`\n")

    with open_redshift() as conn:
        # 1. Listar tablas
        all_tables = list_all_tables(conn)
        if args.schema:
            all_tables = all_tables[all_tables["table_schema"] == args.schema]
        if args.table:
            all_tables = all_tables[all_tables["table_name"] == args.table]

        print(f"Tablas a explorar: {len(all_tables)}\n")
        md_sections.append(f"\n**Tablas exploradas:** {len(all_tables)}\n")

        # Indice por schema
        md_sections.append("\n## Indice\n")
        for sch in all_tables["table_schema"].unique():
            md_sections.append(f"\n### {sch}\n")
            for t in all_tables[all_tables["table_schema"] == sch]["table_name"]:
                md_sections.append(f"- [`{sch}.{t}`](#{sch}-{t})")

        # 2. Por cada tabla, sacar columnas + count
        for i, row in enumerate(all_tables.itertuples(), 1):
            sch = row.table_schema
            t = row.table_name
            print(f"[{i}/{len(all_tables)}] {sch}.{t}", flush=True)
            try:
                cols_df = list_columns(conn, sch, t)
                n_rows = None if args.quick else get_row_count_for_mandant(conn, sch, t)
                md_sections.extend(render_table_md(sch, t, cols_df, n_rows))

                ts = get_timestamp_columns(cols_df)
                print(f"   {len(cols_df)} cols · {n_rows or '?'} filas · "
                      f"timestamps: {ts[:3]}")
            except Exception as e:
                print(f"   ERROR: {e}")
                md_sections.append(f"\n## `{sch}.{t}`\n\nERROR: `{e}`\n")

    OUTPUT.write_text("\n".join(md_sections), encoding="utf-8")

    print(f"\n[OK] Schema remoto -> {OUTPUT}")
    print("\nProximos pasos:")
    print(f"  1. Revisar {OUTPUT.name} para entender estructura real")
    print(f"  2. Ajustar config/tables.yml con watermarks correctos")
    print(f"  3. Correr: python -m pipelines.bronze.full_load")


if __name__ == "__main__":
    main()
