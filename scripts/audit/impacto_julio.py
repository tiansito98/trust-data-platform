# -*- coding: utf-8 -*-
"""Impacto en julio 2026 de (a) la inversion entrega/devolucion y (b) los
codigos OT/FI ausentes de COMISIONABLES."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
import pandas as pd
from claims_julio import ASESORES

OUT = os.path.join(os.path.dirname(__file__), 'out')
TASA = 0.05 * 1.19
COMISIONABLES = ["AD", "BF", "LD", "BS", "UP", "CS", "BC", "PF", "SL"]
EXTRA = ["OT", "FI"]

j = pd.read_csv(os.path.join(OUT, 'julio.csv'))
trm = dict(pd.read_csv(os.path.join(OUT, 'trm.csv'))[['fecha', 'trm_cop_per_usd']].values)
j['cop_ban'] = j.subtotal_usd * j.fecha_handover_real.map(trm)
j = j[j.subtotal_usd > 0]
# pure counter: nada prepagado
pure = j[(j.prepagado_cargo_cop.fillna(0) == 0)].copy()

def base(df, codes, col, code):
    s = df[(df[col] == code) & (df.cargo_codigo.isin(codes))]
    return s.cop_ban.sum() * TASA

rows = []
for a, meta in ASESORES.items():
    c = float(meta['codigo'])
    hoy      = base(pure, COMISIONABLES, 'operador_handover_codigo', c)
    corr     = base(pure, COMISIONABLES, 'operador_checkout_codigo', c)
    corr_ext = base(pure, COMISIONABLES + EXTRA, 'operador_checkout_codigo', c)
    rows.append([a, meta['nombre'], round(hoy), round(corr), round(corr - hoy),
                 round(corr_ext), round(corr_ext - hoy)])
r = pd.DataFrame(rows, columns=['asesor', 'nombre', 'comision_hoy',
                                'comision_corregida', 'delta_por_inversion',
                                'corregida_+OT/FI', 'delta_total'])
pd.set_option('display.width', 200)
print('COMISION JULIO 2026 (COP) - regla 5% sobre counter con IVA, TRM Banrep')
print(r.to_string(index=False))
print()
tot = pure[pure.cargo_codigo.isin(EXTRA)]
print(f"Cargos OT/FI pure-counter de julio (los 4 asesores): "
      f"{len(tot)} lineas, comision no pagada = {tot.cop_ban.sum()*TASA:,.0f} COP")
print()
n_dif = j.groupby('numero_contrato').first()
n_dif = (n_dif.operador_handover_codigo != n_dif.operador_checkout_codigo).sum()
print(f"Contratos julio (4 asesores) donde entrega != devolucion: "
      f"{n_dif} de {j.numero_contrato.nunique()}")
