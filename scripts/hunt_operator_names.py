"""
Busqueda EXHAUSTIVA de cualquier columna que pueda contener nombres de
operadores en el datashare de Sixt.

Estrategias:
  1. Buscar columnas con patrones alemanes (Sixt es aleman: bediener, mitarb...)
  2. Buscar TODA columna que termine en _name, _user, _by
  3. Sample datos reales en las tablas que tienen filas para 409
  4. Revisar ge_dim_translations (diccionario maestro) por si decodifica oprt
  5. Listar TODAS las tablas con datos para 409 + sus columnas tipo varchar

Correr:
    python scripts/hunt_operator_names.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipelines._common import open_redshift, query_redshift, mandant_code  # noqa: E402

MNDT = mandant_code()


def main():
    print("=" * 80)
    print("  HUNT - busqueda EXHAUSTIVA de columnas con nombres de operadores")
    print(f"  Mandant: {MNDT}")
    print("=" * 80)

    with open_redshift() as conn:

        # ====================================================================
        # 1. Patrones alemanes (Sixt es aleman)
        # ====================================================================
        print("\n[1] Columnas/tablas con patrones ALEMANES")
        print("-" * 80)
        df = query_redshift(conn, """
            SELECT schema_name, table_name, column_name, data_type
            FROM SVV_REDSHIFT_COLUMNS
            WHERE schema_name NOT IN ('information_schema', 'pg_catalog')
              AND schema_name NOT LIKE 'pg_%'
              AND schema_name NOT LIKE 'sys_%'
              AND (LOWER(column_name) ~ '(bediener|mitarbeiter|personal|verkaufer|berater)'
                OR LOWER(table_name) ~ '(bediener|mitarbeiter|personal|verkaufer|berater)')
            ORDER BY 1, 2, 3
        """)
        if df.empty:
            print("  Ninguna columna/tabla con patrones alemanes")
        else:
            print(df.to_string(index=False))

        # ====================================================================
        # 2. Todas las columnas que terminan en _name, _user, _by_name
        # ====================================================================
        print("\n[2] Columnas que terminan en _name, _user, _by, _person")
        print("-" * 80)
        df = query_redshift(conn, """
            SELECT schema_name, table_name, column_name, data_type
            FROM SVV_REDSHIFT_COLUMNS
            WHERE schema_name NOT IN ('information_schema', 'pg_catalog')
              AND schema_name NOT LIKE 'pg_%'
              AND schema_name NOT LIKE 'sys_%'
              AND (LOWER(column_name) ~ '(_name|_user|_by_|_person|_assignee|_creator|_owner)$'
                OR LOWER(column_name) LIKE '%first_name%'
                OR LOWER(column_name) LIKE '%last_name%'
                OR LOWER(column_name) LIKE '%full_name%')
            ORDER BY 1, 2, 3
        """)
        if df.empty:
            print("  ninguna")
        else:
            print(df.to_string(index=False))

        # ====================================================================
        # 3. ge_dim_translations - posible diccionario decodificador
        # ====================================================================
        print("\n[3] ge_dim_translations (diccionario)")
        print("-" * 80)
        try:
            cols = query_redshift(conn, """
                SELECT column_name, data_type
                FROM SVV_REDSHIFT_COLUMNS
                WHERE schema_name = 'common_shop'
                  AND table_name = 'ge_dim_translations'
                ORDER BY ordinal_position
            """)
            print("  Columnas:")
            print(cols.to_string(index=False))

            n = query_redshift(conn, "SELECT COUNT(*) AS n FROM common_shop.ge_dim_translations").iloc[0]["n"]
            print(f"  Filas totales: {n}")

            sample = query_redshift(conn, """
                SELECT * FROM common_shop.ge_dim_translations LIMIT 5
            """)
            print(f"\n  Sample 5 filas:")
            print(sample.to_string(index=False))
        except Exception as e:
            print(f"  ERROR: {e}")

        # ====================================================================
        # 4. ge_gen_parameter - parametros generales
        # ====================================================================
        print("\n[4] ge_gen_parameter (parametros generales)")
        print("-" * 80)
        try:
            cols = query_redshift(conn, """
                SELECT column_name, data_type
                FROM SVV_REDSHIFT_COLUMNS
                WHERE schema_name = 'common_shop'
                  AND table_name = 'ge_gen_parameter'
                ORDER BY ordinal_position
            """)
            print("  Columnas:")
            print(cols.to_string(index=False))

            n = query_redshift(conn, "SELECT COUNT(*) AS n FROM common_shop.ge_gen_parameter").iloc[0]["n"]
            print(f"  Filas totales: {n}")

            sample = query_redshift(conn, """
                SELECT * FROM common_shop.ge_gen_parameter LIMIT 10
            """)
            print(f"\n  Sample 10 filas:")
            print(sample.to_string(index=False))
        except Exception as e:
            print(f"  ERROR: {e}")

        # ====================================================================
        # 5. Para CADA tabla con datos 409, lista cols varchar > 30 (candidatas a nombres)
        # ====================================================================
        print("\n[5] Tablas con datos 409 + columnas varchar(>30) (candidatas a nombres)")
        print("-" * 80)
        # Primero: que tablas tienen datos 409? (intentamos con mndt_code)
        # Usamos las tablas que ya sabemos que tienen datos
        tablas_con_409 = [
            ("common_shop", "br_dim_branches"),
            ("common_shop", "mn_dim_mandants"),
            ("customer_shop", "pa_dim_partners_franchise"),
            ("customer_shop", "pa_dim_agencies_franchise"),
            ("fleet_shop", "ve_dim_vehicle_groups_franchise"),
            ("fleet_shop", "ve_dim_vehicles"),
            ("fleet_shop", "ve_fct_vehicles_current"),
            ("rent_shop", "ra_fct_rentals_vwt_franchise"),
            ("rent_shop", "ra_fct_rental_vehicles_franchise"),
            ("rent_shop", "rs_fct_reservations"),
            ("rent_shop", "ch_fct_ra_charges_franchise"),
            ("rent_shop", "ch_fct_rs_charges_franchise"),
            ("rent_shop", "rt_dim_rates_franchise"),
        ]
        for schema, table in tablas_con_409:
            df = query_redshift(conn, f"""
                SELECT column_name, data_type
                FROM SVV_REDSHIFT_COLUMNS
                WHERE schema_name = '{schema}'
                  AND table_name = '{table}'
                  AND data_type LIKE 'character varying%'
                ORDER BY ordinal_position
            """)
            # Filtrar columnas con length > 30 (probable de texto largo, candidato a nombre)
            df_filt = df[
                df["data_type"].str.contains(r"\(\d+\)", regex=True)
            ]
            # Heuristica: solo columnas varchar grandes que podrian tener nombres
            interesting = df_filt[
                df_filt["data_type"].str.extract(r"\((\d+)\)")[0].astype(int).between(30, 500)
            ]
            if not interesting.empty:
                print(f"\n  [{schema}.{table}]")
                print(interesting.to_string(index=False))

        # ====================================================================
        # 6. ALL columns in ra_fct_rentals_vwt - busca cualquiera con name
        # ====================================================================
        print("\n[6] TODAS las columnas en ra_fct_rentals_vwt_franchise (174 cols)")
        print("    Buscando cualquiera que pueda tener nombre/staff/operator")
        print("-" * 80)
        df = query_redshift(conn, """
            SELECT column_name, data_type
            FROM SVV_REDSHIFT_COLUMNS
            WHERE schema_name = 'rent_shop'
              AND table_name = 'ra_fct_rentals_vwt_franchise'
              AND data_type LIKE 'character varying%'
            ORDER BY column_name
        """)
        print(df.to_string(index=False))


if __name__ == "__main__":
    main()
