# -*- coding: utf-8 -*-
"""Baja a CSV el detalle silver de los contratos reclamados (query indexada, liviana)."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
import pandas as pd
from sqlalchemy import text
from pipelines._common import get_engine
from claims_julio import todos_los_contratos

OUT = os.path.join(os.path.dirname(__file__), 'out')
os.makedirs(OUT, exist_ok=True)
ids = todos_los_contratos()
e = get_engine('silver,operational,public')

det = pd.read_sql(text("""
    SELECT numero_contrato, numero_reserva, fuente_cargo, cargo_inty, cargo_codigo,
           cargo_descripcion, cargo_categoria, cargo_posicion, cargo_correccion,
           cantidad, subtotal_cop, subtotal_usd,
           prepagado_cargo_cop, counter_cargo_cop, bucket_pago,
           forma_pago_cargo_codigo, canal_cobro_tarifa, tipo_agencia_main, tercero_nombre,
           operador_handover_codigo, operador_checkout_codigo,
           fecha_handover_real, fecha_devolucion_real, dias_renta,
           sede_handover, placa, estado_rental, trm_aplicada
    FROM silver.vw_rentals_detail
    WHERE numero_contrato = ANY(:ids)
    ORDER BY numero_contrato, fuente_cargo, cargo_inty, cargo_posicion
"""), e, params={"ids": ids})
det.to_csv(os.path.join(OUT, 'detail.csv'), index=False, encoding='utf-8')
print('detail rows:', len(det), '| contratos presentes:', det.numero_contrato.nunique(), '/', len(ids))
falt = set(ids) - set(det.numero_contrato.unique())
print('faltantes en silver:', sorted(falt))
