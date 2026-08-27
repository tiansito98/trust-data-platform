"""
Chequea columnas nuevas de Sixt en tablas de bronze.
Compara lo que Sixt tiene HOY vs lo que bronze tiene localmente,
listando las columnas que faltan (nuevas en Redshift, no en bronze).

Correr:
    python scripts/check_new_columns.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipelines._common import open_redshift, query_redshift, get_engine  # noqa: E402
from sqlalchemy import text  # noqa: E402

# Tablas mas criticas — donde queremos ver si hay columnas nuevas
TABLAS = [
    ("rent_shop", "ra_fct_rentals_vwt_franchise"),
    ("rent_shop", "rs_fct_reservations"),
    ("rent_shop", "ch_fct_ra_charges_franchise"),
    ("rent_shop", "ch_fct_rs_charges_franchise"),
    ("rent_shop", "ra_fct_rental_vehicles_franchise"),
]


def get_redshift_cols(conn, schema, table):
    # SVV_REDSHIFT_COLUMNS no tiene character_maximum_length — el tipo ya
    # viene con la longitud embebida (ej. "character varying(45)").
    df = query_redshift(conn, f"""
        SELECT column_name, data_type
        FROM SVV_REDSHIFT_COLUMNS
        WHERE schema_name = '{schema}'
          AND table_name = '{table}'
        ORDER BY ordinal_position
    """)
    return df


def get_bronze_cols(engine, table_bronze):
    import pandas as pd
    with engine.connect() as conn:
        df = pd.read_sql_query(text("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'bronze'
              AND table_name = :t
            ORDER BY ordinal_position
        """), conn, params={"t": table_bronze})
    return df


def main():
    print("=" * 90)
    print("  CHEQUEO DE COLUMNAS NUEVAS EN SIXT vs BRONZE")
    print("=" * 90)

    engine = get_engine("bronze")

    with open_redshift() as conn:
        for schema, table in TABLAS:
            table_bronze = f"{schema}_{table}"
            print(f"\n[{schema}.{table}]")
            print("-" * 90)

            try:
                rs_cols = get_redshift_cols(conn, schema, table)
                br_cols = get_bronze_cols(engine, table_bronze)

                rs_set = set(rs_cols["column_name"].tolist())
                br_set = set(br_cols["column_name"].tolist())

                nuevas = rs_set - br_set
                borradas = br_set - rs_set

                if nuevas:
                    print(f"  [NUEVAS EN SIXT — FALTAN EN BRONZE] ({len(nuevas)}):")
                    for col in sorted(nuevas):
                        row = rs_cols[rs_cols["column_name"] == col].iloc[0]
                        dt = row["data_type"]
                        print(f"    {col:50} {dt}")
                    print(f"\n  SQL para agregarlas:")
                    for col in sorted(nuevas):
                        row = rs_cols[rs_cols["column_name"] == col].iloc[0]
                        dt_raw = str(row["data_type"]).strip().lower()
                        # Map Redshift data_type string a Postgres.
                        # dt_raw ejemplos: "character varying(45)", "bigint",
                        # "numeric(10,0)", "timestamp without time zone", etc.
                        if "character varying" in dt_raw or dt_raw.startswith("varchar"):
                            # Extraer longitud si esta entre parentesis
                            if "(" in dt_raw and ")" in dt_raw:
                                length = dt_raw[dt_raw.index("(")+1:dt_raw.index(")")]
                                pg_type = f"VARCHAR({length})"
                            else:
                                pg_type = "TEXT"
                        elif dt_raw.startswith("bigint"):
                            pg_type = "BIGINT"
                        elif dt_raw.startswith("integer") or dt_raw == "int":
                            pg_type = "INTEGER"
                        elif dt_raw.startswith("smallint"):
                            pg_type = "SMALLINT"
                        elif dt_raw.startswith("numeric") or dt_raw.startswith("decimal"):
                            # Preservar precision(scale) si existe
                            if "(" in dt_raw:
                                pg_type = "NUMERIC" + dt_raw[dt_raw.index("("):]
                            else:
                                pg_type = "NUMERIC"
                        elif "timestamp" in dt_raw:
                            pg_type = "TIMESTAMP"
                        elif dt_raw == "date":
                            pg_type = "DATE"
                        elif dt_raw == "boolean":
                            pg_type = "BOOLEAN"
                        elif dt_raw == "text":
                            pg_type = "TEXT"
                        elif dt_raw.startswith("character(") or dt_raw.startswith("char("):
                            # character(N) fijo
                            length = dt_raw[dt_raw.index("(")+1:dt_raw.index(")")]
                            pg_type = f"CHAR({length})"
                        else:
                            pg_type = dt_raw.upper()
                        print(f"    ALTER TABLE bronze.{table_bronze} "
                              f"ADD COLUMN IF NOT EXISTS {col} {pg_type};")

                if borradas:
                    print(f"\n  [EN BRONZE PERO NO EN SIXT] ({len(borradas)}) — no urgente:")
                    for col in sorted(borradas):
                        print(f"    {col}")

                if not nuevas and not borradas:
                    print("  [OK] Bronze sincronizado con Sixt")
            except Exception as e:
                print(f"  [ERROR] {e}")


if __name__ == "__main__":
    main()
