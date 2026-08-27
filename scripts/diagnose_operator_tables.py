"""
Diagnostico de tablas candidatas para mapear oprt_bed (codigo) -> nombre.

Para cada tabla de la lista de candidatas:
  1. Cuenta filas para mandant 409
  2. Lista columnas (id + name) si las tiene
  3. Samplea 5 filas mostrando codigos de operador
  4. Compara conjunto de codigos de operador con los de ra_fct_rentals

Correr:
    python scripts/diagnose_operator_tables.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipelines._common import open_redshift, query_redshift, mandant_code  # noqa: E402

MNDT = mandant_code()


# (schema, table, oprt_columns, name_columns_if_any, has_mndt_filter)
CANDIDATES = [
    ("common_shop", "br_dim_branches",
     ["brnc_operator"],
     ["brnc_manager_first_name", "brnc_manager_last_name",
      "brnc_area_director_first_name", "brnc_area_director_last_name"],
     True),

    ("common_shop", "ge_otm_remarks",
     ["oprt_bed"],
     [],
     True),

    ("common_shop", "dm_dim_damage_cases_history",
     ["oprt_bed_created_by", "oprt_bed_modified_by", "oprt_bed_reported_by"],
     [],
     False),  # confirmar

    ("damage_shop", "dm_fct_damages",
     ["oprt_bed", "oprt_bed_remark"],
     [],
     True),

    ("damage_shop", "dm_fct_damage_details_franchise",
     ["oprt_bed", "oprt_bed2"],
     [],
     True),

    ("rent_shop", "rs_fct_reservations",
     ["rsrv_staff_number"],
     [],
     True),

    ("common_shop", "et_fct_key_handovers",
     [],  # no oprt_bed directo
     [],  # tampoco columnas name, ya verificado
     True),

    ("common_shop", "et_fct_turnaround_tasks",
     ["etrt_task_assigned_agent_id", "etrt_created_by_id",
      "etrt_started_by_id", "etrt_completed_by_id"],
     ["etrt_assigned_agent_name", "etrt_created_by_name",
      "etrt_started_by_name", "etrt_completed_by_name"],
     True),
]


def count_rows(conn, schema, table, has_mndt):
    """Cuenta filas para mandant 409 (o todas si no tiene filtro)."""
    where = f"WHERE mndt_code = {MNDT}" if has_mndt else ""
    try:
        df = query_redshift(conn, f"SELECT COUNT(*) AS n FROM {schema}.{table} {where}")
        return int(df.iloc[0]["n"])
    except Exception as e:
        # Reintenta sin filtro de mandant
        try:
            df = query_redshift(conn, f"SELECT COUNT(*) AS n FROM {schema}.{table}")
            return int(df.iloc[0]["n"])
        except Exception as e2:
            return f"ERROR: {e2}"


def sample_operators(conn, schema, table, oprt_cols, name_cols, has_mndt, limit=10):
    """Trae sample de operadores distintos con nombres si los hay."""
    if not oprt_cols:
        return None
    cols = oprt_cols + name_cols
    select_clause = ", ".join(cols)
    where_parts = []
    if has_mndt:
        where_parts.append(f"mndt_code = {MNDT}")
    where_parts.append(f"{oprt_cols[0]} IS NOT NULL")
    where = "WHERE " + " AND ".join(where_parts)
    try:
        df = query_redshift(conn, f"""
            SELECT DISTINCT {select_clause}
            FROM {schema}.{table}
            {where}
            ORDER BY {oprt_cols[0]}
            LIMIT {limit}
        """)
        return df
    except Exception as e:
        return f"ERROR: {e}"


def get_known_operators(conn):
    """Trae los codigos de operador que ya conocemos de ra_fct_rentals (silver source)."""
    try:
        df = query_redshift(conn, f"""
            SELECT DISTINCT oprt_bed AS codigo
            FROM rent_shop.ra_fct_rentals_vwt_franchise
            WHERE mndt_code = {MNDT}
              AND oprt_bed IS NOT NULL
              AND oprt_bed > 0
            ORDER BY codigo
        """)
        return set(df["codigo"].astype(int).tolist())
    except Exception as e:
        print(f"  ERROR cargando codigos conocidos: {e}")
        return set()


def main():
    print("=" * 80)
    print("  DIAGNOSTICO DE TABLAS CANDIDATAS PARA MAPEO OPERADOR -> NOMBRE")
    print(f"  Mandant: {MNDT} (Colombia)")
    print("=" * 80)

    with open_redshift() as conn:
        # Primero: que operadores conocemos de rentals
        print("\n[Paso 1] Operadores conocidos en ra_fct_rentals_vwt_franchise:")
        known = get_known_operators(conn)
        print(f"  -> {len(known)} codigos distintos de operador en rentals")
        if known:
            sample_known = sorted(known)[:20]
            print(f"  Sample: {sample_known}")

        # Para cada candidata
        for schema, table, oprt_cols, name_cols, has_mndt in CANDIDATES:
            print("\n" + "-" * 80)
            print(f"[{schema}.{table}]")
            n = count_rows(conn, schema, table, has_mndt)
            print(f"  Filas para mandant {MNDT}: {n}")

            if isinstance(n, str) or n == 0:
                print(f"  -> SKIP (sin datos)")
                continue

            print(f"  Columnas operador: {oprt_cols or '(ninguna)'}")
            print(f"  Columnas nombre:   {name_cols or '(ninguna)'}")

            if not oprt_cols:
                print(f"  -> SKIP (no tiene columnas oprt)")
                continue

            sample = sample_operators(conn, schema, table, oprt_cols, name_cols, has_mndt)
            if isinstance(sample, str):
                print(f"  {sample}")
                continue
            if sample is None or sample.empty:
                print(f"  -> sin codigos de operador no nulos")
                continue

            print(f"\n  Sample ({len(sample)} filas distintas):")
            print(sample.to_string(index=False))

            # Compara con los conocidos de rentals
            if known and oprt_cols:
                try:
                    found = set(
                        int(v) for v in sample[oprt_cols[0]].dropna().tolist()
                    )
                    overlap = found & known
                    print(f"\n  Overlap con codigos de rentals: {len(overlap)}/{len(found)}")
                    if overlap:
                        print(f"    -> {sorted(overlap)[:10]}")
                except (ValueError, TypeError) as e:
                    print(f"  (no se pudo comparar: {e})")

        # CRUCIAL: et_fct_turnaround_tasks SIN filtro de mandant.
        # Si Sixt usa IDs globales para staff, podrian aparecer nombres
        # de operadores de OTRO pais que coincidan con nuestros oprt_bed.
        print("\n" + "=" * 80)
        print("[BONUS] et_fct_turnaround_tasks SIN filtro de mandant")
        print("        (chequeo si los IDs de Sixt son globales)")
        print("=" * 80)

        try:
            df_global = query_redshift(conn, """
                SELECT etrt_task_assigned_agent_id, etrt_assigned_agent_name,
                       COUNT(*) AS tareas, MAX(brnc_code) AS sample_branch
                FROM common_shop.et_fct_turnaround_tasks
                WHERE etrt_task_assigned_agent_id IS NOT NULL
                  AND etrt_assigned_agent_name IS NOT NULL
                GROUP BY etrt_task_assigned_agent_id, etrt_assigned_agent_name
                ORDER BY tareas DESC
                LIMIT 30
            """)
            if df_global.empty:
                print("  Tabla et_fct_turnaround_tasks esta vacia globalmente.")
            else:
                print(f"  {len(df_global)} agentes con tareas (sample top 30):")
                print(df_global.to_string(index=False))

                if known:
                    found = set(
                        int(v) for v in df_global["etrt_task_assigned_agent_id"]
                        .dropna().tolist()
                    )
                    overlap = found & known
                    print(f"\n  *** OVERLAP con codigos de rentals CO: "
                          f"{len(overlap)}/{len(found)} ***")
                    if overlap:
                        print(f"    -> {sorted(overlap)[:20]}")
                        print("    >>> POSIBLE MATCH: Sixt usa IDs globales y "
                              "podemos sacar nombres de tareas hechas en otros paises")
                    else:
                        print("    -> 0 overlap: IDs de turnaround NO matchean oprt_bed de CO. "
                              "Sistemas separados.")
        except Exception as e:
            print(f"  ERROR: {e}")

        print("\n" + "=" * 80)
        print("  CONCLUSION:")
        print("  - Las tablas con datos para 409 + columna name + oprt nos sirven")
        print("  - Las tablas con datos para 409 pero sin name no sirven directo")
        print("  - Las tablas con 0 filas para 409 estan vacias en CO")
        print("  - El BONUS chequea si IDs son globales (turnaround en otros paises)")
        print("=" * 80)


if __name__ == "__main__":
    main()
