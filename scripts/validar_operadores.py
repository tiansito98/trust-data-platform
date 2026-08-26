# -*- coding: utf-8 -*-
"""
Validacion post-rebuild de la correccion de operador (2026-08-26).

Comprueba contra silver ya reconstruido que:
  1. La columna nueva existe y la vieja ya no.
  2. operador_handover_codigo = quien ENTREGA (oprt_bed_handover del primer tramo).
  3. operador_devolucion_codigo = quien RECIBE.
  4. Los contratos de la auditoria de julio quedaron con el asesor correcto.

    python scripts/validar_operadores.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from sqlalchemy import text

from pipelines._common import get_engine

# contrato -> asesor que lo ENTREGO (validado a mano en la auditoria de julio)
ESPERADO = {
    9523774314: 7793224,   # Jeimmy Fajardo (Steffany)
    9523826011: 7792174,   # Natalia Quintero
    9523848159: 7795534,   # David Bonilla
    9523897935: 7795534,   # David Bonilla
    9523923550: 7797448,   # Samantha Castillo
    9524049080: 7795534,   # David Bonilla
}


def main():
    e = get_engine("silver,bronze")
    fallos = []

    cols = pd.read_sql(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'silver' AND table_name = 'vw_rentals_full'
          AND column_name LIKE 'operador%'
    """), e).column_name.tolist()
    print("1. Columnas de operador en vw_rentals_full:", cols)
    if "operador_devolucion_codigo" not in cols:
        fallos.append("falta operador_devolucion_codigo")
    if "operador_checkout_codigo" in cols:
        fallos.append("operador_checkout_codigo sigue existiendo (rebuild no corrio?)")

    df = pd.read_sql(text("""
        WITH veh AS (
            SELECT DISTINCT ON (rntl_mvnr) rntl_mvnr, oprt_bed_handover
            FROM silver.fact_rental_vehicles ORDER BY rntl_mvnr, rvnc_hser
        )
        SELECT COUNT(*) AS contratos,
               COUNT(*) FILTER (
                   WHERE f.operador_handover_codigo IS DISTINCT FROM v.oprt_bed_handover
                     AND v.oprt_bed_handover IS NOT NULL
               ) AS no_coinciden,
               COUNT(*) FILTER (WHERE f.operador_handover_codigo IS NULL) AS sin_operador
        FROM silver.vw_rentals_full f
        JOIN veh v ON v.rntl_mvnr = f.numero_contrato
        WHERE f.fecha_handover_real >= DATE '2026-01-01'
    """), e).iloc[0]
    print(f"\n2. Contratos 2026: {df.contratos:,} | no coinciden con la tabla de "
          f"vehiculos: {df.no_coinciden} | sin operador: {df.sin_operador}")
    if df.no_coinciden:
        fallos.append(f"{df.no_coinciden} contratos con handover distinto al de origen")

    print("\n3. Contratos de la auditoria de julio:")
    chk = pd.read_sql(text("""
        SELECT numero_contrato, operador_handover_codigo AS entrego,
               operador_devolucion_codigo AS recibio
        FROM silver.vw_rentals_full WHERE numero_contrato = ANY(:ids)
        ORDER BY numero_contrato
    """), e, params={"ids": [float(k) for k in ESPERADO]})
    for r in chk.itertuples(index=False):
        esp = ESPERADO[int(r.numero_contrato)]
        ok = int(r.entrego) == esp if pd.notna(r.entrego) else False
        print(f"   {int(r.numero_contrato)}  entrego={r.entrego}  "
              f"esperado={esp}  recibio={r.recibio}  {'OK' if ok else 'FALLA'}")
        if not ok:
            fallos.append(f"contrato {int(r.numero_contrato)} mal atribuido")

    print("\n" + ("TODO OK" if not fallos else "FALLAS:\n  - " + "\n  - ".join(fallos)))
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
