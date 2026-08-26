# -*- coding: utf-8 -*-
"""
Aplica en la base la regla de periodos de contrato (2026-08-26).

Reconstruye vw_rentals_detail para que exponga la columna nueva cargo_periodo
(= chra_mser), y valida el resultado.

    python scripts/aplicar_regla_periodo.py

Contexto: un contrato modificado/extendido republica sus cargos en periodos
nuevos (mser 0, 1, 2...). No son duplicados: la suma de todos los periodos es el
total que reporta Sixt. Cuentan completos como ingreso, pero solo el periodo 0
comisiona, porque la extension arrastra el adicional sola y el asesor no lo
vuelve a vender.

Solo hace falta vw_rentals_detail: vw_rentals_resumen lee columnas explicitas de
detail y no cambia de contenido, y ninguna otra vista depende de detail
(verificado en pg_depend). Correrlo dos veces no rompe nada.

ORDEN IMPORTANTE: esto va ANTES del push del dashboard. Agregar una columna es
compatible con el codigo que hay en produccion; al reves, la pagina pediria una
columna que todavia no existe.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from sqlalchemy import text

from pipelines._common import get_engine
from pipelines.silver.build import build_rentals_detail

TASA = 0.05 * 1.19
COMISIONABLES = ("AD", "BF", "LD", "BS", "UP", "CS", "BC", "PF", "SL")


def main():
    engine = get_engine("silver,bronze")

    print("=" * 70)
    print("  Reconstruyendo vw_rentals_detail (agrega cargo_periodo)")
    print("=" * 70)
    t = time.time()
    build_rentals_detail(engine)
    print(f"\n   listo en {time.time() - t:.1f}s\n")

    fallos = []

    cols = pd.read_sql(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'silver' AND table_name = 'vw_rentals_detail'
          AND column_name = 'cargo_periodo'
    """), engine)
    print(f"1. Columna cargo_periodo presente: {not cols.empty}")
    if cols.empty:
        fallos.append("no se creo cargo_periodo")
        print("\nFALLA: " + fallos[0])
        return 1

    ej = pd.read_sql(text("""
        SELECT cargo_codigo, cargo_periodo, cantidad, subtotal_usd
        FROM silver.vw_rentals_detail
        WHERE numero_contrato = 9523788459 AND fuente_cargo = 'RENTAL_COUNTER'
        ORDER BY cargo_posicion, cargo_periodo
    """), engine)
    print("\n2. Contrato 9523788459 (el que reviso la manager):")
    print(ej.to_string(index=False))
    if sorted(ej.cargo_periodo.dropna().unique().tolist()) != [0, 1]:
        fallos.append("9523788459 no quedo con periodos 0 y 1")

    tot = pd.read_sql(text("""
        SELECT COUNT(DISTINCT numero_contrato) AS contratos_multiperiodo
        FROM silver.vw_rentals_detail WHERE cargo_periodo > 0
    """), engine).iloc[0]
    print(f"\n3. Contratos multi-periodo en silver: {tot.contratos_multiperiodo}")

    delta = pd.read_sql(text("""
        SELECT d.numero_contrato, d.cargo_codigo,
               ROUND(SUM(d.counter_cargo_usd * t.trm_cop_per_usd * 0.0595)::numeric, 0)
                   AS comision_que_ya_no_se_paga
        FROM silver.vw_rentals_detail d
        LEFT JOIN silver.dim_trm_diaria t ON t.fecha = d.fecha_handover_real::date
        WHERE d.fuente_cargo = 'RENTAL_COUNTER'
          AND d.cargo_periodo > 0
          AND d.cargo_codigo = ANY(:com)
          AND d.counter_cargo_usd > 0.01
          AND COALESCE(d.prepagado_cargo_usd, 0) < 0.01
          AND d.fecha_handover_real >= DATE '2026-01-01'
        GROUP BY 1, 2 ORDER BY 1
    """), engine, params={"com": list(COMISIONABLES)})
    print("\n4. Extensiones de 2026 que dejan de comisionar:")
    print(delta.to_string(index=False) if not delta.empty else "   (ninguna)")

    print("\n" + ("TODO OK — ya puedes hacer el push del dashboard"
                  if not fallos else "FALLAS:\n  - " + "\n  - ".join(fallos)))
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
