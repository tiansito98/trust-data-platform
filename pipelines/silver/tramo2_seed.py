"""
Seed inicial de tablas operativas Tramo 2 con data dummy realista.

Permite tener data en op_* para validar el dashboard antes de que Trust
empiece a llenarlas con formularios reales.

Correr:
    python -m pipelines.silver.tramo2_seed --demo  (poblado con data dummy)
    python -m pipelines.silver.tramo2_seed --truncate  (vaciar todo, dejar schema)
"""
from __future__ import annotations

import argparse
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pipelines._common import open_local  # noqa: E402

random.seed(42)


def truncate_all(con):
    op_tables = [
        "op_cierre_diario_sede",
        "op_novedades_vehiculo",
        "op_incidentes",
        "op_checklist_apertura_cierre",
        "op_traslado_vehiculos",
        "op_solicitudes_soporte",
        "op_contratos_soportes_faltantes",
    ]
    for t in op_tables:
        try:
            con.execute(f"DELETE FROM {t}")
            print(f"  truncated {t}")
        except Exception as e:
            print(f"  skip {t} ({e})")


def seed_demo(con):
    """Genera ~6 meses de data realista en tablas op_*."""
    print("\n>> Seeding op_* tables con data dummy")
    print("   Implementacion completa pendiente; ver trust_demo/scripts/02_seed_dummy_data.py")
    print("   como referencia. Aqui debe portarse adaptado para DuckDB + sedes reales de Trust.")

    # TODO: portar la lógica de seed del proyecto trust_demo/, ajustando para:
    #   - Usar las sedes reales que aparezcan en bronze.common_shop_br_dim_branches
    #   - Usar vehículos reales de bronze.fleet_shop_ve_fct_vehicles_current
    #   - Usar empleados de una tabla dim_employee_trust (a crear)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--demo", action="store_true", help="Poblar con data dummy")
    p.add_argument("--truncate", action="store_true", help="Vaciar todas las op_*")
    args = p.parse_args()

    con = open_local("silver")

    if args.truncate:
        truncate_all(con)
        con.commit()
    elif args.demo:
        seed_demo(con)
        con.commit()
    else:
        p.print_help()

    con.close()


if __name__ == "__main__":
    main()
