"""
Explorador de Bronze - genera un data dictionary automatico de las tablas locales.

Para cada tabla en bronze.db produce:
  - Metadata estructural (columnas, tipos, nullability)
  - Estadisticas por columna (% null, cardinalidad, min/max, sample values)
  - Identificacion de columnas categoricas (cardinalidad baja)
  - Identificacion de candidatos a watermark (timestamps)
  - Identificacion de candidatos a primary key (cardinalidad = N filas)

Output:
  - Imprime resumen en consola
  - Guarda data dictionary completo en docs/data_dictionary.md
  - Guarda inferencia de watermarks/PKs en docs/inferred_watermarks.yml

Correr:
    python -m pipelines.bronze.explore
    python -m pipelines.bronze.explore --table rent_shop_rs_fct_reservations
    python -m pipelines.bronze.explore --quick   (skip estadisticas pesadas)
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pipelines._common import BRONZE_DB, ROOT, open_local  # noqa: E402

DOCS_DIR = ROOT / "docs"
DOCS_DIR.mkdir(exist_ok=True)
DICT_OUTPUT = DOCS_DIR / "data_dictionary.md"
INFERRED_OUTPUT = DOCS_DIR / "inferred_watermarks.yml"

# Cardinalidad maxima para considerar una columna "categorica"
CATEGORICAL_THRESHOLD = 20

# Para evitar queries pesadas en columnas altamente cardinales
SAMPLE_VALUES_LIMIT = 5


def list_tables(con) -> list[str]:
    rows = con.execute("""
        SELECT name FROM sqlite_master
        WHERE type = 'table'
          AND name NOT LIKE 'sqlite_%'
          AND name NOT LIKE 'ctrl_%'
        ORDER BY name
    """).fetchall()
    return [r[0] for r in rows]


def describe_columns(con, table: str) -> pd.DataFrame:
    """Devuelve metadata estructural de columnas (column_name, column_type)."""
    rows = con.execute(f'PRAGMA table_info("{table}")').fetchall()
    # PRAGMA table_info devuelve: cid, name, type, notnull, dflt_value, pk
    return pd.DataFrame(
        [{"column_name": r[1], "column_type": r[2] or "TEXT"} for r in rows]
    )


def get_row_count(con, table: str) -> int:
    return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def column_stats(con, table: str, col: str, col_type: str, total_rows: int, quick: bool) -> dict:
    """Estadisticas por columna - null count, cardinalidad, min/max, sample values."""
    stats = {
        "column": col,
        "type": col_type,
        "null_count": 0,
        "null_pct": 0.0,
        "cardinality": None,
        "min": None,
        "max": None,
        "sample_values": [],
        "is_categorical": False,
        "is_timestamp": False,
        "watermark_candidate": False,
        "pk_candidate": False,
    }

    # Null count
    try:
        n_null = con.execute(f'SELECT COUNT(*) FROM "{table}" WHERE "{col}" IS NULL').fetchone()[0]
        stats["null_count"] = int(n_null)
        stats["null_pct"] = round(n_null * 100.0 / total_rows, 2) if total_rows else 0.0
    except Exception:
        pass

    if quick:
        return stats

    # Cardinality
    try:
        cardinality = con.execute(f'SELECT COUNT(DISTINCT "{col}") FROM "{table}"').fetchone()[0]
        stats["cardinality"] = int(cardinality)

        # PK candidate: cardinalidad = total rows AND null_count = 0
        if cardinality == total_rows and stats["null_count"] == 0 and total_rows > 0:
            stats["pk_candidate"] = True

        # Categorica: cardinalidad baja (no boolean ni enums infinitos)
        if 1 < cardinality <= CATEGORICAL_THRESHOLD and total_rows > cardinality * 5:
            stats["is_categorical"] = True
    except Exception:
        pass

    # Min/Max para tipos comparables
    type_lower = col_type.lower()
    is_numeric = any(t in type_lower for t in ["int", "double", "decimal", "float", "real"])
    is_temporal = any(t in type_lower for t in ["timestamp", "date", "time"])
    stats["is_timestamp"] = is_temporal

    if is_numeric or is_temporal:
        try:
            row = con.execute(
                f'SELECT MIN("{col}"), MAX("{col}") FROM "{table}" WHERE "{col}" IS NOT NULL'
            ).fetchone()
            stats["min"] = str(row[0]) if row[0] is not None else None
            stats["max"] = str(row[1]) if row[1] is not None else None
        except Exception:
            pass

    # Sample values para categoricas y otras
    if stats["is_categorical"] or (stats["cardinality"] and stats["cardinality"] <= 100):
        try:
            rows = con.execute(f"""
                SELECT "{col}", COUNT(*) AS n
                FROM "{table}"
                WHERE "{col}" IS NOT NULL
                GROUP BY "{col}"
                ORDER BY n DESC
                LIMIT {SAMPLE_VALUES_LIMIT}
            """).fetchall()
            stats["sample_values"] = [(str(v), int(n)) for v, n in rows]
        except Exception:
            pass
    elif total_rows > 0:
        # Para columnas no categoricas, traer 3 valores random
        try:
            rows = con.execute(
                f'SELECT DISTINCT "{col}" FROM "{table}" WHERE "{col}" IS NOT NULL LIMIT 3'
            ).fetchall()
            stats["sample_values"] = [(str(v[0]), None) for v in rows]
        except Exception:
            pass

    # Watermark candidate: timestamp con cardinalidad alta y prefijos comunes
    if is_temporal and stats["cardinality"] and stats["cardinality"] > total_rows * 0.5:
        # Preferimos columnas con sufijo _datm, _date, _upd
        if any(p in col.lower() for p in ["_datm", "_date", "upd", "modified", "changed"]):
            stats["watermark_candidate"] = True

    return stats


def render_table_section(table: str, total_rows: int, stats_list: list[dict]) -> str:
    md = []
    md.append(f"\n## `{table}`\n")
    md.append(f"**Filas:** {total_rows:,}\n")

    pk_candidates = [s["column"] for s in stats_list if s["pk_candidate"]]
    if pk_candidates:
        md.append(f"**Posibles PK:** `{', '.join(pk_candidates)}`\n")

    wm_candidates = [s["column"] for s in stats_list if s["watermark_candidate"]]
    if wm_candidates:
        md.append(f"**Posibles watermark:** `{', '.join(wm_candidates)}`\n")

    cat_candidates = [s["column"] for s in stats_list if s["is_categorical"]]
    if cat_candidates:
        md.append(f"**Columnas categoricas:** `{', '.join(cat_candidates)}`\n")

    md.append("\n### Columnas\n")
    md.append("| Columna | Tipo | % Null | Cardinalidad | Min | Max | Sample values |")
    md.append("|---|---|---:|---:|---|---|---|")

    for s in stats_list:
        sample = ""
        if s["sample_values"]:
            if s["sample_values"][0][1] is not None:
                # Con conteos
                sample = ", ".join([f"`{v}` ({n})" for v, n in s["sample_values"]])
            else:
                sample = ", ".join([f"`{v[0]}`" for v in s["sample_values"]])

        flags = []
        if s["pk_candidate"]: flags.append("PK?")
        if s["watermark_candidate"]: flags.append("WM?")
        if s["is_categorical"]: flags.append("CAT")
        flag_str = " ".join(flags)

        col_label = f"`{s['column']}`"
        if flag_str:
            col_label += f"<br>**{flag_str}**"

        md.append(
            f"| {col_label} | `{s['type']}` | "
            f"{s['null_pct']}% | "
            f"{s['cardinality'] if s['cardinality'] is not None else '?'} | "
            f"{s['min'] or ''} | "
            f"{s['max'] or ''} | "
            f"{sample[:150]} |"
        )

    return "\n".join(md)


def render_inferred_watermarks(table_stats: dict) -> str:
    """Genera un YAML con los watermarks/PKs inferidos para copiar en config/tables.yml."""
    lines = ["# Watermarks y PKs inferidos automaticamente desde explore.py", ""]
    lines.append(f"# Generado: {datetime.now().isoformat()}")
    lines.append("")
    lines.append("inferred:")
    for table, stats_list in table_stats.items():
        pks = [s["column"] for s in stats_list if s["pk_candidate"]]
        wms = [s["column"] for s in stats_list if s["watermark_candidate"]]
        lines.append(f"")
        lines.append(f"  {table}:")
        lines.append(f"    pk: {pks}")
        lines.append(f"    watermark_candidates: {wms}")
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--table", default=None, help="Solo procesar una tabla especifica")
    p.add_argument("--quick", action="store_true",
                   help="Skip estadisticas pesadas (cardinality, min/max, samples)")
    p.add_argument("--limit", type=int, default=None,
                   help="Limitar a N tablas (para testing)")
    args = p.parse_args()

    if not BRONZE_DB.exists():
        print(f"[X] No existe {BRONZE_DB}")
        print("    Corre primero: python -m pipelines.bronze.full_load")
        sys.exit(1)

    print("=" * 70)
    print(f"  EXPLORE BRONZE - generando data dictionary")
    print(f"  archivo:  {BRONZE_DB}")
    print(f"  output:   {DICT_OUTPUT}")
    print(f"  modo:     {'quick (rapido)' if args.quick else 'completo'}")
    print("=" * 70)

    con = open_local("bronze", read_only=True)
    tables = list_tables(con) if not args.table else [args.table]
    if args.limit:
        tables = tables[:args.limit]

    print(f"\nTablas a procesar: {len(tables)}\n")

    md_sections = []
    md_sections.append(f"# Data Dictionary - Bronze\n")
    md_sections.append(f"\n> Generado automaticamente desde `pipelines/bronze/explore.py` "
                       f"el {datetime.now().strftime('%Y-%m-%d %H:%M')}.\n")
    md_sections.append(f"\n**Archivo origen:** `{BRONZE_DB.name}` "
                       f"({BRONZE_DB.stat().st_size / 1024 / 1024:.1f} MB)\n")
    md_sections.append(f"\n**Tablas:** {len(tables)}\n")

    md_sections.append("\n## Convenciones de las flags\n")
    md_sections.append("- **PK?** = posible primary key (cardinalidad = total rows, sin nulls)")
    md_sections.append("- **WM?** = posible watermark column para incremental (timestamp con cardinalidad alta)")
    md_sections.append("- **CAT** = columna categorica (cardinalidad <= 20)\n")

    md_sections.append("\n## Indice\n")
    for t in tables:
        md_sections.append(f"- [`{t}`](#{t.replace('_', '-')})")

    table_stats_dict = {}

    for i, t in enumerate(tables, 1):
        print(f"[{i}/{len(tables)}] {t}", flush=True)
        try:
            cols = describe_columns(con, t)
            total = get_row_count(con, t)

            stats_list = []
            for _, row in cols.iterrows():
                col_name = row["column_name"]
                col_type = row["column_type"]
                # Skip metadata columns que agregamos en Bronze
                if col_name in ("_loaded_at", "_source_table"):
                    continue
                stats = column_stats(con, t, col_name, col_type, total, args.quick)
                stats_list.append(stats)

            table_stats_dict[t] = stats_list
            md_sections.append(render_table_section(t, total, stats_list))

            # Resumen consola
            pk = [s["column"] for s in stats_list if s["pk_candidate"]]
            wm = [s["column"] for s in stats_list if s["watermark_candidate"]]
            cat = [s["column"] for s in stats_list if s["is_categorical"]]
            print(f"   filas: {total:,}  cols: {len(stats_list)}  "
                  f"PK?: {pk[:2]}  WM?: {wm[:2]}  CAT: {len(cat)}")

        except Exception as e:
            print(f"   ERROR: {e}")
            md_sections.append(f"\n## `{t}`\n\nERROR durante exploracion: `{e}`\n")

    con.close()

    # Escribir data dictionary
    DICT_OUTPUT.write_text("\n".join(md_sections), encoding="utf-8")
    print(f"\n[OK] data dictionary -> {DICT_OUTPUT}")

    # Escribir watermarks inferidos
    yaml_content = render_inferred_watermarks(table_stats_dict)
    INFERRED_OUTPUT.write_text(yaml_content, encoding="utf-8")
    print(f"[OK] watermarks inferidos -> {INFERRED_OUTPUT}")

    print("\n" + "=" * 70)
    print("  EXPLORE COMPLETO")
    print("=" * 70)
    print("\nProximos pasos:")
    print(f"  1. Revisar {DICT_OUTPUT.name}")
    print(f"  2. Comparar inferred_watermarks.yml con config/tables.yml")
    print(f"  3. Ajustar config/tables.yml con los watermarks reales")


if __name__ == "__main__":
    main()
