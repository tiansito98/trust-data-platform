# -*- coding: utf-8 -*-
"""Compara oprt_bed / oprt_bed_checkout (rentals) contra oprt_bed_handover / oprt_bed_return
(rental_vehicles) para los contratos reclamados. Query indexada por mvnr."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
import pandas as pd
from sqlalchemy import text
from pipelines._common import get_engine
from claims_julio import todos_los_contratos

OUT = os.path.join(os.path.dirname(__file__), 'out')
ids = [float(i) for i in todos_los_contratos()]
e = get_engine('bronze,public')

df = pd.read_sql(text("""
    SELECT r.rntl_mvnr::bigint          AS numero_contrato,
           r.oprt_bed::bigint           AS rentals_oprt_bed,
           r.oprt_bed_checkout::bigint  AS rentals_oprt_bed_checkout,
           v.oprt_bed_handover::bigint  AS veh_oprt_bed_handover,
           v.oprt_bed_return::bigint    AS veh_oprt_bed_return,
           v.rvnc_handover_datm, v.rvnc_return_datm,
           r.rntl_handover_datm, r.rntl_return_datm, r.rntl_creating_date
    FROM bronze.rent_shop_ra_fct_rentals_vwt_franchise r
    LEFT JOIN bronze.rent_shop_ra_fct_rental_vehicles_franchise v
           ON v.mndt_code = r.mndt_code AND v.rntl_mvnr = r.rntl_mvnr
          AND v.vhcl_int_num = r.vhcl_int_num
    WHERE r.mndt_code = 409 AND r.rntl_mvnr = ANY(:ids)
    ORDER BY 1
"""), e, params={"ids": ids})
df.to_csv(os.path.join(OUT, 'operators.csv'), index=False)
pd.set_option('display.width', 250); pd.set_option('display.max_columns', 30)
print(df.to_string())
