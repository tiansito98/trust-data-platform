# -*- coding: utf-8 -*-
"""
Para cada cargo reclamado (excluyendo OT y FI): determinar
  1. si el cargo es REALMENTE de counter (o venia de la reserva = prepagado)
  2. a quien le pertenece REALMENTE (operador de entrega, fuente robusta)
  3. que dice el sistema hoy
Trabaja sobre bronze deduplicado, para que el bug de duplicados no contamine.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
import pandas as pd
from sqlalchemy import text
from pipelines._common import get_engine
from claims_julio import ASESORES

OUT = os.path.join(os.path.dirname(__file__), 'out')
TASA = 0.05 * 1.19

# Cargos reclamados, ya desagregados por codigo y sin OT/FI.
# (asesor, contrato_escrito, contrato_real, codigo, valor_reclamado_de_la_linea)
LINEAS = [
    ("STEFFANY", 9523774314, 9523774314, "BF",   8954),
    ("STEFFANY", 9523781208, 9523781208, "LD", 123845),
    ("STEFFANY", 9523898459, None,       "BF", 121860),
    ("STEFFANY", 9523845472, 9523845472, "SL",   4130),
    ("STEFFANY", 9523910889, 9523910889, "LD",   4852),
    ("STEFFANY", 9523923550, 9523923550, "CS",   9583),
    ("STEFFANY", 9523929866, 9523929866, "SL",   2717),

    ("DANILO",   9524024893, 9524024893, "BF",   8023),
    ("DANILO",   9523986328, 9523986328, "BF",  None),   # linea "BF AD" = 61.727 juntos
    ("DANILO",   9523986328, 9523986328, "AD",  None),
    ("DANILO",   9523875927, 9523875927, "BF",  12183),
    ("DANILO",   9523826906, 9523826906, "BF",  21019),
    ("DANILO",   9523771679, 9523771679, "AD",  None),   # linea "OT AD" = 9.029 juntos

    ("NATALIA",  9523849946, 9523849946, "BF",  59512),
    ("NATALIA",  9523854552, 9523854552, "AD",   4870),
    ("NATALIA",  9523853782, 9523853782, "SL",   2706),
    ("NATALIA",  9523886016, 9523886016, "BF",  28429),
    ("NATALIA",  9523895564, 9523895564, "BF",  11709),
    ("NATALIA",  9523963080, 9523963080, "SL",  13588),
    ("NATALIA",  9523986588, 9523986588, "SL",   4006),
    ("NATALIA",  9524046682, 9524046682, "SL",   1335),

    ("DAVID",    9523813233, 9523813233, "AD",  None),   # linea "AD OT" = 14.430 juntos
    ("DAVID",    9524049080, 9524049080, "SL",  None),   # linea "SL BC" = 2.280 juntos
    ("DAVID",    9524049080, 9524049080, "BC",  None),
    ("DAVID",    9523848159, 9523848159, "SL",  None),   # linea "SL BC" = 9.500 juntos
    ("DAVID",    9523848159, 9523848159, "BC",  None),
    ("DAVID",    9523909872, 9523897935, "LD",  12200),
    ("DAVID",    9523962548, 9523962548, "BF",  None),   # linea "BF OT" = 13.664 juntos
]

ids = sorted({r[2] for r in LINEAS if r[2]})
e = get_engine('silver,bronze,public')

# --- cargos RA deduplicados + su contraparte en la reserva (RS) ---
ra = pd.read_sql(text("""
    WITH ra AS (
        SELECT DISTINCT ON (chra_mvnr, chra_konr, chra_inty, chra_pos)
               chra_mvnr, chra_konr, chra_inty, chra_pos, chra_chco,
               chra_anz1, chra_value_rental
        FROM bronze.rent_shop_ch_fct_ra_charges_franchise
        WHERE mndt_code = 409 AND chra_mvnr = ANY(:ids)
        ORDER BY chra_mvnr, chra_konr, chra_inty, chra_pos, pk
    ),
    maxk AS (SELECT chra_mvnr, MAX(chra_konr) k FROM ra GROUP BY 1),
    vig AS (
        SELECT ra.* FROM ra JOIN maxk ON maxk.chra_mvnr = ra.chra_mvnr
        WHERE ra.chra_konr = maxk.k
    )
    SELECT v.chra_mvnr::bigint      AS contrato,
           v.chra_inty              AS inty,
           v.chra_chco              AS codigo,
           v.chra_anz1              AS unidades,
           v.chra_value_rental      AS valor_usd,
           r.rsrv_resn::bigint      AS reserva,
           rs.rs_usd                AS valor_en_reserva_usd
    FROM vig v
    JOIN bronze.rent_shop_ra_fct_rentals_vwt_franchise r
      ON r.rntl_mvnr = v.chra_mvnr AND r.mndt_code = 409
    LEFT JOIN (
        SELECT chrs_resn, chrs_inty, chrs_chco, SUM(chrs_value_rental) AS rs_usd
        FROM (SELECT DISTINCT ON (chrs_resn, chrs_konr, chrs_inty, chrs_pos)
                     chrs_resn, chrs_konr, chrs_inty, chrs_pos, chrs_chco, chrs_value_rental
              FROM bronze.rent_shop_ch_fct_rs_charges_franchise
              WHERE mndt_code = 409
              ORDER BY chrs_resn, chrs_konr, chrs_inty, chrs_pos, pk) d
        GROUP BY 1,2,3
    ) rs ON rs.chrs_resn = r.rsrv_resn AND rs.chrs_inty = v.chra_inty
        AND rs.chrs_chco = v.chra_chco
"""), e, params={"ids": [float(i) for i in ids]})

# --- operadores reales + contexto del contrato ---
ctx = pd.read_sql(text("""
    WITH veh AS (
        SELECT DISTINCT ON (rntl_mvnr) rntl_mvnr, oprt_bed_handover::bigint AS entrego
        FROM bronze.rent_shop_ra_fct_rental_vehicles_franchise
        WHERE mndt_code = 409 ORDER BY rntl_mvnr, rvnc_hser
    ),
    vehr AS (
        SELECT DISTINCT ON (rntl_mvnr) rntl_mvnr, oprt_bed_return::bigint AS recibio
        FROM bronze.rent_shop_ra_fct_rental_vehicles_franchise
        WHERE mndt_code = 409 ORDER BY rntl_mvnr, rvnc_hser DESC
    )
    SELECT r.rntl_mvnr::bigint AS contrato, v.entrego, vr.recibio,
           r.oprt_bed::bigint  AS acredita_hoy,
           r.rsrv_resn::bigint AS reserva,
           r.rntl_handover_datm::date AS fecha,
           t.trm_cop_per_usd   AS trm
    FROM bronze.rent_shop_ra_fct_rentals_vwt_franchise r
    LEFT JOIN veh  v  ON v.rntl_mvnr  = r.rntl_mvnr
    LEFT JOIN vehr vr ON vr.rntl_mvnr = r.rntl_mvnr
    LEFT JOIN silver.dim_trm_diaria t ON t.fecha = r.rntl_handover_datm::date
    WHERE r.mndt_code = 409 AND r.rntl_mvnr = ANY(:ids)
"""), e, params={"ids": [float(i) for i in ids]})

ra.to_csv(os.path.join(OUT, 'ra_dedup.csv'), index=False)
ctx.to_csv(os.path.join(OUT, 'ctx.csv'), index=False)
print('cargos vigentes deduplicados:', len(ra))
print(ctx.to_string(index=False))
