"""
Explora las tablas FI (finance) que pueden contener mapeo empleado -> nombre.

El hunt anterior encontro:
  common_shop.fi_dim_cc_hierarchy_attrs.empl_personal_number_manager (varchar 80)
  common_shop.fi_dim_cc_hierarchy_attrs.empl_manager_name (varchar 272)

Esto literalmente dice "Employee Personal Number" — puede ser la tabla maestra.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipelines._common import open_redshift, query_redshift, mandant_code  # noqa: E402

MNDT = mandant_code()


def explore_table(conn, schema, table):
    print(f"\n{'=' * 80}")
    print(f"  {schema}.{table}")
    print('=' * 80)

    # Columnas
    cols = query_redshift(conn, f"""
        SELECT ordinal_position, column_name, data_type
        FROM SVV_REDSHIFT_COLUMNS
        WHERE schema_name = '{schema}'
          AND table_name = '{table}'
        ORDER BY ordinal_position
    """)
    print(f"\n  Total columnas: {len(cols)}")
    print(cols.to_string(index=False))

    # Count total (sin filtro)
    try:
        n = query_redshift(conn, f"SELECT COUNT(*) AS n FROM {schema}.{table}").iloc[0]["n"]
        print(f"\n  Filas totales (sin filtro): {n:,}")
    except Exception as e:
        print(f"\n  ERROR count: {e}")
        return

    if n == 0:
        print("  -> Tabla vacia, skip sample")
        return

    # Sample primeras 10 filas
    try:
        print(f"\n  Sample 10 filas:")
        sample = query_redshift(conn, f"SELECT * FROM {schema}.{table} LIMIT 10")
        # Limit to first 8 columns for readability
        if len(sample.columns) > 8:
            print(f"  (mostrando solo primeras 8 columnas de {len(sample.columns)})")
            print(sample.iloc[:, :8].to_string(index=False))
        else:
            print(sample.to_string(index=False))
    except Exception as e:
        print(f"  ERROR sample: {e}")


def main():
    print("=" * 80)
    print("  EXPLORE - tablas FI candidatas a empleados maestros")
    print(f"  Mandant: {MNDT}")
    print("=" * 80)

    candidates = [
        ("common_shop", "fi_dim_cc_hierarchy_attrs"),
        ("common_shop", "fi_dim_costcenter_hierarchies"),
        ("common_shop", "fi_dim_alternative_costcenter_hierarchies"),
        ("common_shop", "fi_dim_costcenters"),
    ]

    with open_redshift() as conn:
        for schema, table in candidates:
            try:
                explore_table(conn, schema, table)
            except Exception as e:
                print(f"\n  [{schema}.{table}] ERROR: {e}")

        # Si fi_dim_cc_hierarchy_attrs tiene datos, sample especifico
        # de las columnas empl_*
        print("\n" + "=" * 80)
        print("  SAMPLE ESPECIFICO: empl_* en fi_dim_cc_hierarchy_attrs")
        print("=" * 80)
        try:
            df = query_redshift(conn, """
                SELECT DISTINCT
                    empl_personal_number_manager,
                    empl_manager_name,
                    ccha_name,
                    ccha_organisation_name
                FROM common_shop.fi_dim_cc_hierarchy_attrs
                WHERE empl_personal_number_manager IS NOT NULL
                LIMIT 30
            """)
            if df.empty:
                print("  Sin datos en columnas empl_*")
            else:
                print(f"  {len(df)} empleados distintos:")
                print(df.to_string(index=False))
        except Exception as e:
            print(f"  ERROR: {e}")

        # Tambien revisar si fi_dim_cc_hierarchy_attrs tiene mndt_code o algo similar
        print("\n" + "=" * 80)
        print("  ¿fi_dim_cc_hierarchy_attrs tiene filtro de mandant?")
        print("=" * 80)
        try:
            df = query_redshift(conn, """
                SELECT column_name
                FROM SVV_REDSHIFT_COLUMNS
                WHERE schema_name = 'common_shop'
                  AND table_name = 'fi_dim_cc_hierarchy_attrs'
                  AND (LOWER(column_name) LIKE '%mandant%'
                    OR LOWER(column_name) LIKE '%country%'
                    OR LOWER(column_name) LIKE '%mndt%'
                    OR LOWER(column_name) LIKE '%region%'
                    OR LOWER(column_name) LIKE '%market%')
            """)
            if df.empty:
                print("  No tiene columnas de mandant/country -> tabla global")
            else:
                print(df.to_string(index=False))
                # Intenta filtrar por las columnas que aparezcan
                for col in df["column_name"]:
                    try:
                        d = query_redshift(conn, f"""
                            SELECT DISTINCT {col}
                            FROM common_shop.fi_dim_cc_hierarchy_attrs
                            WHERE {col} IS NOT NULL
                            LIMIT 20
                        """)
                        print(f"\n  Valores distintos en {col}:")
                        print(d.to_string(index=False))
                    except Exception as e:
                        print(f"  ERROR sampling {col}: {e}")
        except Exception as e:
            print(f"  ERROR: {e}")


if __name__ == "__main__":
    main()
