"""
Busca en TODO el Redshift de Sixt cualquier columna que pueda contener
nombres de operadores/empleados, para identificar si existe una tabla que
nos permita mapear oprt_bed (codigo numerico) a nombre.

Correr:
    python scripts/find_operator_columns.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipelines._common import open_redshift, query_redshift  # noqa: E402


def main():
    print("=" * 80)
    print("  BUSQUEDA DE COLUMNAS OPERATOR / EMPLOYEE / NAME en Redshift Sixt")
    print("=" * 80)

    sql = """
        SELECT schema_name, table_name, column_name, data_type
        FROM SVV_REDSHIFT_COLUMNS
        WHERE LOWER(column_name) ~ '(first_name|last_name|full_name|fullname|employee|operator|oprt_name|user_name|asesor|agent_name|staff)'
           OR LOWER(table_name) ~ '(employee|operator|staff|personnel|user|asesor|hr_)'
        ORDER BY schema_name, table_name, column_name
    """

    with open_redshift() as conn:
        df = query_redshift(conn, sql)

    if df.empty:
        print("\n  [NINGUNA TABLA tiene columnas de operator/employee/name]")
        print("  Sixt no expone tabla de operadores via datashare.")
        print("  -> Mapeo debe ser manual via Boomerang/Sixt central.")
    else:
        print(f"\n  Encontradas {len(df)} columnas/tablas candidatas:\n")
        print(df.to_string(index=False))

    print("\n" + "=" * 80)
    print("  BUSQUEDA AMPLIA: columnas que mencionen 'oprt' en cualquier tabla")
    print("=" * 80)

    sql2 = """
        SELECT schema_name, table_name, column_name, data_type
        FROM SVV_REDSHIFT_COLUMNS
        WHERE LOWER(column_name) LIKE '%oprt%'
        ORDER BY schema_name, table_name, column_name
    """
    with open_redshift() as conn:
        df2 = query_redshift(conn, sql2)

    print(f"\n  {len(df2)} columnas mencionan 'oprt':\n")
    print(df2.to_string(index=False))


if __name__ == "__main__":
    main()
