# -*- coding: utf-8 -*-
"""Comision julio 2026 con el operador de ENTREGA tomado de la fuente robusta
(rental_vehicles.oprt_bed_handover del primer tramo), vs la atribucion actual."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
import pandas as pd
from sqlalchemy import text
from pipelines._common import get_engine
from claims_julio import ASESORES

OUT = os.path.join(os.path.dirname(__file__), 'out')
TASA = 0.05 * 1.19
COMISIONABLES = ["AD", "BF", "LD", "BS", "UP", "CS", "BC", "PF", "SL"]
EXTRA = ["OT", "FI"]

e = get_engine('silver,bronze,public')
df = pd.read_sql(text("""
    WITH veh AS (
        SELECT DISTINCT ON (rntl_mvnr) rntl_mvnr,
               oprt_bed_handover::bigint AS entrega_real
        FROM bronze.rent_shop_ra_fct_rental_vehicles_franchise
        WHERE mndt_code = 409
        ORDER BY rntl_mvnr, rvnc_hser
    )
    SELECT d.numero_contrato, d.cargo_codigo, d.subtotal_usd,
           d.prepagado_cargo_cop, d.fecha_handover_real,
           d.operador_handover_codigo::bigint AS acredita_hoy,
           v.entrega_real,
           ROUND(d.subtotal_usd::numeric * t.trm_cop_per_usd, 0) AS cop_ban
    FROM silver.vw_rentals_detail d
    JOIN veh v ON v.rntl_mvnr = d.numero_contrato
    LEFT JOIN silver.dim_trm_diaria t ON t.fecha = d.fecha_handover_real::date
    WHERE d.fuente_cargo = 'RENTAL_COUNTER'
      AND d.fecha_handover_real BETWEEN DATE '2026-07-01' AND DATE '2026-07-31'
      AND TRIM(COALESCE(d.placa,'')) <> '' AND COALESCE(d.subtotal_usd,0) > 0
"""), e)
df.to_csv(os.path.join(OUT, 'julio_full.csv'), index=False)
pure = df[df.prepagado_cargo_cop.fillna(0) == 0]

def base(codes, col, code):
    s = pure[(pure[col] == code) & (pure.cargo_codigo.isin(codes))]
    return float(s.cop_ban.sum()) * TASA

rows = []
for a, meta in ASESORES.items():
    c = int(meta['codigo'])
    hoy      = base(COMISIONABLES, 'acredita_hoy', c)
    corr     = base(COMISIONABLES, 'entrega_real', c)
    corr_ext = base(COMISIONABLES + EXTRA, 'entrega_real', c)
    rows.append([a, meta['nombre'], round(hoy), round(corr), round(corr - hoy),
                 round(corr_ext), round(corr_ext - hoy)])
r = pd.DataFrame(rows, columns=['asesor', 'nombre', 'comision_hoy', 'corregida',
                                'delta_inversion', 'corregida_+OT_FI', 'delta_total'])
pd.set_option('display.width', 200)
print('COMISION JULIO 2026 (COP) - 5% sobre counter con IVA, TRM Banrep')
print(r.to_string(index=False))
print()
tot = df.numero_contrato.nunique()
dif = df.groupby('numero_contrato').first()
print(f"Contratos julio (toda la sede): {tot} | con entrega != devolucion: "
      f"{(dif.acredita_hoy != dif.entrega_real).sum()} "
      f"({(dif.acredita_hoy != dif.entrega_real).mean()*100:.0f}%)")
print()
print('Bolsa total comisionable julio (toda la sede):')
print(f"  hoy      : {pure[pure.cargo_codigo.isin(COMISIONABLES)].cop_ban.sum()*TASA:,.0f} COP")
print(f"  con OT/FI: {pure[pure.cargo_codigo.isin(COMISIONABLES+EXTRA)].cop_ban.sum()*TASA:,.0f} COP")
