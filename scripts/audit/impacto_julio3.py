# -*- coding: utf-8 -*-
"""Impacto julio 2026 con la regla pure-counter tomada de USD (no de las
columnas COP, que estan bugueadas) y el operador de entrega real."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
import pandas as pd
from sqlalchemy import text
from pipelines._common import get_engine
from claims_julio import ASESORES

OUT = os.path.join(os.path.dirname(__file__), 'out')
TASA = 0.05 * 1.19
COMIS = ["AD", "BF", "LD", "BS", "UP", "CS", "BC", "PF", "SL"]
EXTRA = ["OT", "FI"]

e = get_engine('silver,bronze,public')
df = pd.read_sql(text("""
    WITH veh AS (
        SELECT DISTINCT ON (rntl_mvnr) rntl_mvnr, oprt_bed_handover::bigint AS entrego
        FROM bronze.rent_shop_ra_fct_rental_vehicles_franchise
        WHERE mndt_code = 409 ORDER BY rntl_mvnr, rvnc_hser
    )
    SELECT d.numero_contrato, d.cargo_codigo,
           d.subtotal_usd, d.prepagado_cargo_usd, d.counter_cargo_usd,
           d.operador_handover_codigo::bigint AS acredita_hoy,
           v.entrego,
           ROUND(d.counter_cargo_usd::numeric * t.trm_cop_per_usd, 0) AS counter_cop_ok
    FROM silver.vw_rentals_detail d
    JOIN veh v ON v.rntl_mvnr = d.numero_contrato
    LEFT JOIN silver.dim_trm_diaria t ON t.fecha = d.fecha_handover_real::date
    WHERE d.fuente_cargo = 'RENTAL_COUNTER'
      AND d.fecha_handover_real BETWEEN DATE '2026-07-01' AND DATE '2026-07-31'
      AND TRIM(COALESCE(d.placa,'')) <> '' AND COALESCE(d.subtotal_usd,0) > 0
"""), e)

# PURE COUNTER segun USD: nada prepagado y counter > 0
pure = df[(df.prepagado_cargo_usd.fillna(0).abs() < 0.01) &
          (df.counter_cargo_usd.fillna(0) > 0.01)].copy()

def base(codes, col, code):
    s = pure[(pure[col] == code) & (pure.cargo_codigo.isin(codes))]
    return float(s.counter_cop_ok.sum()) * TASA

rows = []
for a, meta in ASESORES.items():
    c = int(meta['codigo'])
    rows.append([a, meta['nombre'],
                 round(base(COMIS, 'acredita_hoy', c)),
                 round(base(COMIS, 'entrego', c)),
                 round(base(COMIS + EXTRA, 'entrego', c))])
r = pd.DataFrame(rows, columns=['asesor', 'nombre', 'hoy', 'corregida', 'corregida_+OT_FI'])
r['delta'] = r.corregida - r.hoy
pd.set_option('display.width', 200)
print('COMISION JULIO 2026 (COP) - regla pure-counter corregida (USD)')
print(r[['nombre', 'hoy', 'corregida', 'delta', 'corregida_+OT_FI']].to_string(index=False))
print()
print(f"Bolsa comisionable julio, toda la sede: "
      f"{pure[pure.cargo_codigo.isin(COMIS)].counter_cop_ok.sum()*TASA:,.0f} COP "
      f"| con OT/FI: {pure[pure.cargo_codigo.isin(COMIS+EXTRA)].counter_cop_ok.sum()*TASA:,.0f} COP")
print()
print('Comparacion con el calculo anterior (que usaba las columnas COP bugueadas):')
mal = df[df.prepagado_cargo_usd.fillna(0).abs() >= 0.01]
print(f"  filas prepagadas que el filtro viejo contaba como counter: {len(mal)} de {len(df)}")
