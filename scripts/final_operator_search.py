"""
Busqueda FINAL EXHAUSTIVA - todas las columnas posibles donde podria
esconderse el nombre de un asesor.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipelines._common import open_redshift, query_redshift, mandant_code  # noqa: E402

MNDT = mandant_code()


def main():
    print("=" * 80)
    print("  FINAL EXHAUSTIVE SEARCH")
    print("=" * 80)

    with open_redshift() as conn:

        # ============================================================
        # 1. Patrones MUY amplios: cualquier cosa que parezca persona
        # ============================================================
        print("\n[1] Patrones amplios (agent, advisor, asesor, sales rep, etc.)")
        print("-" * 80)
        df = query_redshift(conn, """
            SELECT schema_name, table_name, column_name, data_type
            FROM SVV_REDSHIFT_COLUMNS
            WHERE schema_name NOT IN ('information_schema', 'pg_catalog')
              AND schema_name NOT LIKE 'pg_%'
              AND schema_name NOT LIKE 'sys_%'
              AND (
                LOWER(column_name) ~ '(agent|advisor|asesor|consultor|sales_rep|salesrep|sales_person|salesperson|rep_id|rep_name|rep_code|stf_|emp_)'
                OR LOWER(column_name) ~ '(vorname|nachname|vname|nname|first_n|last_n)'
                OR LOWER(column_name) ~ '(performed_by|done_by|signed_by|recorded_by|noted_by|authored)'
                OR LOWER(column_name) ~ '(handover_by|return_by|created_by|updated_by|modified_by|reported_by|managed_by|opened_by|closed_by)'
              )
            ORDER BY schema_name, table_name, column_name
        """)
        if df.empty:
            print("  ninguna")
        else:
            print(f"  {len(df)} columnas:")
            print(df.to_string(index=False))

        # ============================================================
        # 2. TODAS las 174 columnas de ra_fct_rentals_vwt_franchise
        # ============================================================
        print("\n[2] TODAS las 174 columnas de ra_fct_rentals_vwt_franchise")
        print("-" * 80)
        df = query_redshift(conn, """
            SELECT column_name, data_type
            FROM SVV_REDSHIFT_COLUMNS
            WHERE schema_name = 'rent_shop'
              AND table_name = 'ra_fct_rentals_vwt_franchise'
            ORDER BY column_name
        """)
        print(f"  Total: {len(df)}")
        print(df.to_string(index=False))

        # ============================================================
        # 3. TODAS las 180 columnas de rs_fct_reservations
        # ============================================================
        print("\n[3] TODAS las 180 columnas de rs_fct_reservations")
        print("-" * 80)
        df = query_redshift(conn, """
            SELECT column_name, data_type
            FROM SVV_REDSHIFT_COLUMNS
            WHERE schema_name = 'rent_shop'
              AND table_name = 'rs_fct_reservations'
            ORDER BY column_name
        """)
        print(f"  Total: {len(df)}")
        print(df.to_string(index=False))

        # ============================================================
        # 4. Sample REAL de rs_fct_reservations con TODAS las cols varchar
        #    Tal vez Daniel Tabares aparece en algun campo de texto
        # ============================================================
        print("\n[4] Sample rs_fct_reservations buscando 'Tabares' o 'Quintero' literal")
        print("-" * 80)
        try:
            # Lista columnas varchar para hacer un like multi-columna
            cols_df = query_redshift(conn, """
                SELECT column_name
                FROM SVV_REDSHIFT_COLUMNS
                WHERE schema_name = 'rent_shop'
                  AND table_name = 'rs_fct_reservations'
                  AND data_type LIKE 'character varying%'
                ORDER BY column_name
            """)
            varchar_cols = cols_df["column_name"].tolist()
            # Construye WHERE con OR de cada varchar col LIKE '%Tabares%'
            where_parts = " OR ".join([f"{c} ILIKE '%Tabares%'" for c in varchar_cols])
            sql = f"""
                SELECT rsrv_resn, rsrv_staff_number, *
                FROM rent_shop.rs_fct_reservations
                WHERE mndt_code = {MNDT}
                  AND ({where_parts})
                LIMIT 5
            """
            df = query_redshift(conn, sql)
            if df.empty:
                print("  Nadie llamado 'Tabares' en ninguna columna varchar de reservations")
            else:
                print(f"  ENCONTRADO!! {len(df)} filas con 'Tabares' en alguna columna:")
                print(df.to_string(index=False))
        except Exception as e:
            print(f"  ERROR: {e}")

        # ============================================================
        # 5. Mismo busqueda en ra_fct_rentals_vwt_franchise
        # ============================================================
        print("\n[5] Sample ra_fct_rentals_vwt_franchise buscando 'Tabares' literal")
        print("-" * 80)
        try:
            cols_df = query_redshift(conn, """
                SELECT column_name
                FROM SVV_REDSHIFT_COLUMNS
                WHERE schema_name = 'rent_shop'
                  AND table_name = 'ra_fct_rentals_vwt_franchise'
                  AND data_type LIKE 'character varying%'
                ORDER BY column_name
            """)
            varchar_cols = cols_df["column_name"].tolist()
            where_parts = " OR ".join([f"{c} ILIKE '%Tabares%'" for c in varchar_cols])
            sql = f"""
                SELECT rntl_mvnr, oprt_bed, oprt_bed_checkout, *
                FROM rent_shop.ra_fct_rentals_vwt_franchise
                WHERE mndt_code = {MNDT}
                  AND ({where_parts})
                LIMIT 5
            """
            df = query_redshift(conn, sql)
            if df.empty:
                print("  Nadie llamado 'Tabares' en ninguna columna varchar de rentals")
            else:
                print(f"  ENCONTRADO!! {len(df)} filas con 'Tabares' en alguna columna:")
                print(df.to_string(index=False))
        except Exception as e:
            print(f"  ERROR: {e}")

        # ============================================================
        # 6. Tablas que NUNCA exploramos en common_shop
        # ============================================================
        print("\n[6] Tablas no exploradas en common_shop — chequeo rapido de filas 409")
        print("-" * 80)
        unexplored = [
            "accrual_b2b", "accrual_leisure",
            "bi_logistic_dim_calendar", "bi_logistic_dim_calendar_delivery",
            "br_dim_branches_cluster_extension", "br_dim_branches_hrs",
            "br_dim_holidays", "br_fct_branch_league",
            "br_fct_branch_sizes_leagues", "br_fct_pool_league",
            "br_otm_branch_notes",
            "citie_centre_geocode",
            "countries_classification_subregion",
            "dia_dim_sixtshare",
            "dm_dim_damage_cases_history",
            "et_fct_key_handovers", "et_fct_turnaround_tasks",
            "ge_dim_agegrp_vw", "ge_dim_channels", "ge_dim_countries",
            "ge_dim_currency_conversions", "ge_dim_daily_exchange_rates",
            "ge_dim_dates", "ge_dim_exchange_rates",
            "ge_dim_interval_clusters", "ge_dim_iso_country_codes",
            "ge_dim_monthly_exchange_rates", "ge_dim_translations",
            "ge_dim_vehicle_translations",
            "ge_gen_age_groups", "ge_gen_parameter", "ge_gen_parameter_sxbi",
            "ge_otm_remarks",
            "history_br_dim_branches",
            "mn_fct_cgh_mandants",
            "nuts3_zip_mapping",
            "ra_dim_mandant_utilization_vw",
            "training_base_data",
            "zip_code_digit_mapping", "zip_code_geo_locations",
        ]
        for table in unexplored:
            try:
                # Algunos tienen mndt_code, otros no — usamos sin filtro
                n = query_redshift(
                    conn, f"SELECT COUNT(*) AS n FROM common_shop.{table}"
                ).iloc[0]["n"]
                # Si tiene datos > 0, vale la pena listar columnas con _name
                if int(n) > 0:
                    cols = query_redshift(conn, f"""
                        SELECT column_name
                        FROM SVV_REDSHIFT_COLUMNS
                        WHERE schema_name = 'common_shop'
                          AND table_name = '{table}'
                          AND (LOWER(column_name) LIKE '%name%'
                            OR LOWER(column_name) LIKE '%user%'
                            OR LOWER(column_name) LIKE '%empl%'
                            OR LOWER(column_name) LIKE '%agent%')
                    """)
                    cols_str = ", ".join(cols["column_name"].tolist()) if not cols.empty else "(sin cols nombre)"
                    print(f"  [{table:50}] {n:>10,} filas  cols: {cols_str}")
            except Exception as e:
                print(f"  [{table:50}] ERROR: {type(e).__name__}")


if __name__ == "__main__":
    main()
