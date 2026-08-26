# -*- coding: utf-8 -*-
"""Todos los cargos counter de julio 2026 de los 4 asesores, bajo ambas atribuciones."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
import pandas as pd
from sqlalchemy import text
from pipelines._common import get_engine

OUT = os.path.join(os.path.dirname(__file__), 'out')
CODES = [7793224.0, 7791677.0, 7792174.0, 7795534.0]
e = get_engine('silver,public')

df = pd.read_sql(text("""
    SELECT numero_contrato, cargo_codigo, cargo_descripcion, cargo_inty, cantidad,
           subtotal_cop, subtotal_usd, counter_cargo_cop, prepagado_cargo_cop, bucket_pago,
           canal_cobro_tarifa, operador_handover_codigo, operador_checkout_codigo,
           fecha_handover_real, sede_handover, placa, dias_renta
    FROM silver.vw_rentals_detail
    WHERE fuente_cargo = 'RENTAL_COUNTER'
      AND fecha_handover_real BETWEEN DATE '2026-07-01' AND DATE '2026-07-31'
      AND (operador_handover_codigo = ANY(:c) OR operador_checkout_codigo = ANY(:c))
      AND TRIM(COALESCE(placa,'')) <> ''
"""), e, params={"c": CODES})
df.to_csv(os.path.join(OUT, 'julio.csv'), index=False, encoding='utf-8')
print('rows', len(df), '| contratos', df.numero_contrato.nunique())
