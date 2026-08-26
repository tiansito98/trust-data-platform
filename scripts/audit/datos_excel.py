# -*- coding: utf-8 -*-
"""Reune todos los datos necesarios para el Excel de revision."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
import pandas as pd
from sqlalchemy import text
from pipelines._common import get_engine
from claims_julio import todos_los_contratos

OUT = os.path.join(os.path.dirname(__file__), 'out')
ids = todos_los_contratos() + [9523788459]      # + candidato al contrato inexistente
e = get_engine('silver,bronze,operational,public')

# 1) Cargos del contrato (RA) deduplicados, konr vigente, con su contraparte en la reserva
ra = pd.read_sql(text("""
    WITH ded AS (
        SELECT DISTINCT ON (chra_mvnr, chra_konr, chra_inty, chra_pos)
               chra_mvnr, chra_konr, chra_inty, chra_pos, chra_chco,
               chra_anz1, chra_value_rental
        FROM bronze.rent_shop_ch_fct_ra_charges_franchise
        WHERE mndt_code = 409 AND chra_mvnr = ANY(:ids)
        ORDER BY chra_mvnr, chra_konr, chra_inty, chra_pos, pk
    ),
    maxk AS (SELECT chra_mvnr, MAX(chra_konr) k FROM ded GROUP BY 1),
    vig AS (SELECT d.* FROM ded d JOIN maxk m ON m.chra_mvnr = d.chra_mvnr AND d.chra_konr = m.k),
    rs AS (
        SELECT chrs_resn, chrs_inty, chrs_chco, SUM(chrs_value_rental) AS rs_usd
        FROM (SELECT DISTINCT ON (chrs_resn, chrs_konr, chrs_inty, chrs_pos)
                     chrs_resn, chrs_konr, chrs_inty, chrs_pos, chrs_chco, chrs_value_rental
              FROM bronze.rent_shop_ch_fct_rs_charges_franchise WHERE mndt_code = 409
              ORDER BY chrs_resn, chrs_konr, chrs_inty, chrs_pos, pk) x
        GROUP BY 1,2,3
    )
    SELECT v.chra_mvnr::bigint AS contrato, v.chra_inty AS inty, v.chra_chco AS codigo,
           SUM(v.chra_anz1)            AS unidades,
           SUM(v.chra_value_rental)    AS usd,
           MAX(COALESCE(rs.rs_usd, 0)) AS usd_en_reserva
    FROM vig v
    JOIN bronze.rent_shop_ra_fct_rentals_vwt_franchise r
      ON r.rntl_mvnr = v.chra_mvnr AND r.mndt_code = 409
    LEFT JOIN rs ON rs.chrs_resn = r.rsrv_resn AND rs.chrs_inty = v.chra_inty
                AND rs.chrs_chco = v.chra_chco
    GROUP BY 1,2,3
"""), e, params={"ids": [float(i) for i in ids]})

# 2) Contexto del contrato: quien entrego de verdad, quien recibio, a quien le paga hoy
ctx = pd.read_sql(text("""
    WITH veh AS (
        SELECT DISTINCT ON (rntl_mvnr) rntl_mvnr, oprt_bed_handover::bigint AS entrego
        FROM bronze.rent_shop_ra_fct_rental_vehicles_franchise
        WHERE mndt_code = 409 ORDER BY rntl_mvnr, rvnc_hser
    )
    SELECT r.rntl_mvnr::bigint  AS contrato,
           v.entrego,
           r.oprt_bed::bigint   AS acredita_hoy,
           r.rsrv_resn::bigint  AS reserva,
           r.rntl_handover_datm::date AS fecha_entrega,
           r.rntl_return_datm::date   AS fecha_devolucion,
           r.rntl_rental_days   AS dias,
           t.trm_cop_per_usd    AS trm
    FROM bronze.rent_shop_ra_fct_rentals_vwt_franchise r
    LEFT JOIN veh v ON v.rntl_mvnr = r.rntl_mvnr
    LEFT JOIN silver.dim_trm_diaria t ON t.fecha = r.rntl_handover_datm::date
    WHERE r.mndt_code = 409 AND r.rntl_mvnr = ANY(:ids)
"""), e, params={"ids": [float(i) for i in ids]})

ases = pd.read_sql(text(
    "SELECT codigo_silver, nombres, apellidos FROM operational.op_asesores"), e)

ra.to_csv(os.path.join(OUT, 'x_ra.csv'), index=False, encoding='utf-8')
ctx.to_csv(os.path.join(OUT, 'x_ctx.csv'), index=False, encoding='utf-8')
ases.to_csv(os.path.join(OUT, 'x_ases.csv'), index=False, encoding='utf-8')
print('cargos:', len(ra), '| contratos:', len(ctx), '| asesores:', len(ases))
