# -*- coding: utf-8 -*-
"""
Rebuild parcial de silver tras corregir la inversion entrega/devolucion
(2026-08-26).

Reconstruye SOLO las vistas afectadas por el cambio de operador, en orden de
dependencia. No toca bronze: el arreglo es puro transform, los datos crudos ya
estan bien.

    python scripts/rebuild_operadores.py

Vistas que reconstruye:
    vw_rentals_full             <- aqui vive el fix del operador
    vw_rentals_detail           <- depende de full
    vw_rentals_resumen          <- depende de detail
    vw_disponibilidad_vehiculo_dia  <- usaba oprt_bed directo
    vw_asesor_dias_mes          <- depende de resumen

Las analiticas anuales (kpi_anual, utilizacion, flota_segmento,
kpi_sede_categoria) leen full/resumen pero NO usan columnas de operador, asi
que su contenido no cambia y no hace falta reconstruirlas.

Si prefieres reconstruir todo: python -m pipelines.silver.build (~13 min).
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipelines._common import get_engine
from pipelines.silver.build import (
    build_rentals_full,
    build_rentals_detail,
    build_rentals_resumen,
    build_disponibilidad_vehiculo_dia,
    build_asesor_dias_mes,
)

PASOS = [
    ("vw_rentals_full", build_rentals_full),
    ("vw_rentals_detail", build_rentals_detail),
    ("vw_rentals_resumen", build_rentals_resumen),
    ("vw_disponibilidad_vehiculo_dia", build_disponibilidad_vehiculo_dia),
    ("vw_asesor_dias_mes", build_asesor_dias_mes),
]


def main():
    print("=" * 70)
    print("  REBUILD PARCIAL SILVER - correccion de operador entrega/devolucion")
    print("=" * 70)
    engine = get_engine("silver,bronze")
    t0 = time.time()
    for i, (nombre, fn) in enumerate(PASOS, start=1):
        print(f"\n[{i}/{len(PASOS)}] {nombre}")
        t = time.time()
        fn(engine)
        print(f"    listo en {time.time() - t:.1f}s")
    print("\n" + "=" * 70)
    print(f"  COMPLETO en {time.time() - t0:.1f}s")
    print("=" * 70)
    print("\nValidacion rapida sugerida:")
    print("  python scripts/validar_operadores.py")


if __name__ == "__main__":
    main()
