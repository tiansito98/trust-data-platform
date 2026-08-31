"""
gold_v4_compare.py - PASO 2: gold_carro_dia por SEGMENTO (no por header).

No toca la tabla viva silver.gold_carro_dia (la que lee 9_Analitica). Construye
silver.gold_carro_dia__v4 con la logica nueva y imprime el ANTES/DESPUES para que
Sebastian apruebe antes de publicar.

Cambio unico vs v3: los dias rentados y el revenue se atribuyen a la placa REAL de
cada SEGMENTO (silver.fact_rental_vehicles, grano contrato x rvnc_hser), no a la
placa del header del contrato. El prorrateo 24h, el capado a hoy, la flota (roster
activo) y la logica de traslados quedan IGUAL -> aisla el efecto de la re-atribucion.

Revenue por dia = neto_contrato / N_contrato, con N_contrato = SUM(seg_days 24h de
TODOS los segmentos del contrato). Se emiten dias solo para segmentos cuya placa
esta en el roster activo. Un segmento en sede propia; un traslado (Internal
Products) mueve el carro a su sede de retorno.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pipelines._common import get_engine        # noqa: E402
from sqlalchemy import text                      # noqa: E402
import pandas as pd                              # noqa: E402

GOLD_START = "2024-01-01"

V4_CREATE = f"""
CREATE TABLE silver.gold_carro_dia__v4 AS
WITH roster AS (
    SELECT DISTINCT ON (placa) placa, base_sede, acriss, in_date FROM (
        SELECT NULLIF(TRIM(dv.vhcl_plate),'') placa,
               bb.brnc_name base_sede,
               COALESCE(NULLIF(v.vhcl_group,''), dv.vhcl_group) acriss,
               CASE WHEN dv.vhcl_first_ci_date::date=DATE '1899-12-31' THEN NULL ELSE dv.vhcl_first_ci_date::date END in_date
        FROM bronze.fleet_shop_ve_fct_vehicles_current v
        JOIN silver.dim_vehicles dv ON dv.vhcl_int_num=v.vhcl_int_num
        LEFT JOIN silver.dim_branches bb ON bb.brnc_code=v.brnc_code
        WHERE NULLIF(TRIM(dv.vhcl_plate),'') IS NOT NULL
    ) x WHERE placa IS NOT NULL ORDER BY placa
),
plate AS (
    SELECT DISTINCT ON (vhcl_int_num) vhcl_int_num, NULLIF(TRIM(vhcl_plate),'') placa
    FROM silver.dim_vehicles ORDER BY vhcl_int_num
),
-- segmentos reales por (contrato, hser): placa, fechas y sede de CADA tramo
seg AS (
    SELECT p.placa,
           v.rntl_mvnr numero_contrato,
           v.rvnc_hser,
           v.rvnc_handover_datm ts_ho,
           v.rvnc_handover_datm::date ho_date,
           LEAST(COALESCE(v.rvnc_return_datm, NOW()), NOW())::date ret_date,
           bh.brnc_name sede_ho,
           br.brnc_name sede_ret,
           (r.rate_type_level3_aknm='Internal Products') is_transfer,
           GREATEST(CEIL(EXTRACT(EPOCH FROM (LEAST(COALESCE(v.rvnc_return_datm,NOW()),NOW())
                  - v.rvnc_handover_datm))/86400.0)::int, 1) seg_days
    FROM silver.fact_rental_vehicles v
    JOIN plate p ON p.vhcl_int_num=v.vhcl_int_num
    JOIN bronze.rent_shop_ra_fct_rentals_vwt_franchise r
      ON r.rntl_mvnr=v.rntl_mvnr AND r.mndt_code=409
    LEFT JOIN silver.dim_branches bh ON bh.brnc_code=v.brnc_code_handover
    LEFT JOIN silver.dim_branches br ON br.brnc_code=v.brnc_code_return
    WHERE v.mndt_code=409 AND p.placa IN (SELECT placa FROM roster)
),
-- N por contrato = suma de dias 24h de TODOS los segmentos (roster o no) -> el
-- neto se reparte exacto y no se infla si una placa de reemplazo esta defleeted
ctr AS (
    SELECT rntl_mvnr numero_contrato,
           SUM(GREATEST(CEIL(EXTRACT(EPOCH FROM (LEAST(COALESCE(rvnc_return_datm,NOW()),NOW())
                  - rvnc_handover_datm))/86400.0)::int,1)) n_contract
    FROM silver.fact_rental_vehicles WHERE mndt_code=409 GROUP BY 1
),
resumen AS (
    SELECT rf.numero_contrato,
           COALESCE(rs.neto_usd,0) neto,
           COALESCE((SELECT trm_cop_per_usd FROM silver.dim_trm_diaria t WHERE t.fecha=rf.fecha_handover_real::date),0) trm
    FROM silver.vw_rentals_full rf
    LEFT JOIN silver.vw_rentals_resumen rs ON rs.numero_contrato=rf.numero_contrato
),
-- ubicacion por placa: cada segmento es un evento, traslado va a sede de retorno
iv AS (
    SELECT placa,
           CASE WHEN is_transfer THEN sede_ret ELSE sede_ho END sede,
           ho_date loc_from,
           LEAD(ho_date) OVER (PARTITION BY placa ORDER BY ho_date, ts_ho) loc_to
    FROM seg
),
first_ho AS (
    SELECT DISTINCT ON (placa) placa, sede_ho FROM seg ORDER BY placa, ts_ho
),
-- dias rentados: solo rentas (no traslados), 24h por SEGMENTO, capado a hoy
rented AS (
    SELECT s.placa, (s.ho_date+gs)::date fecha,
           res.neto/NULLIF(ctr.n_contract,0) rev_usd,
           (res.neto*res.trm)/NULLIF(ctr.n_contract,0) rev_cop
    FROM seg s
    JOIN ctr ON ctr.numero_contrato=s.numero_contrato
    JOIN resumen res ON res.numero_contrato=s.numero_contrato
    CROSS JOIN generate_series(0, s.seg_days-1) gs
    WHERE NOT s.is_transfer AND s.ho_date>=DATE '{GOLD_START}' AND (s.ho_date+gs)<=CURRENT_DATE
),
rented_agg AS (
    SELECT placa, fecha, SUM(rev_usd) rev_usd, SUM(rev_cop) rev_cop, COUNT(*) rentas_dia
    FROM rented GROUP BY placa, fecha
),
fleet AS (
    SELECT r.placa, gs::date fecha
    FROM roster r CROSS JOIN generate_series(
        GREATEST(COALESCE(r.in_date,DATE '{GOLD_START}'), DATE '{GOLD_START}'), CURRENT_DATE, INTERVAL '1 day') gs
),
spine AS (
    SELECT placa, fecha FROM fleet
    UNION
    SELECT placa, fecha FROM rented_agg
)
SELECT s.placa, s.fecha,
       COALESCE(
         (SELECT iv.sede FROM iv WHERE iv.placa=s.placa AND iv.loc_from<=s.fecha
            AND (iv.loc_to IS NULL OR s.fecha<iv.loc_to) ORDER BY iv.loc_from DESC LIMIT 1),
         (SELECT fh.sede_ho FROM first_ho fh WHERE fh.placa=s.placa),
         ro.base_sede, 'SIN_SEDE') sede,
       COALESCE(ro.acriss,'NA') acriss,
       CASE WHEN ra.placa IS NOT NULL THEN 1 ELSE 0 END rented_day,
       COALESCE(ra.rentas_dia,0) rentas_dia,
       COALESCE(ra.rev_usd,0) rev_usd, 0::numeric tar_usd, 0::numeric adi_usd,
       COALESCE(ra.rev_cop,0) rev_cop, 0::numeric tar_cop, 0::numeric adi_cop
FROM spine s
JOIN roster ro ON ro.placa=s.placa
LEFT JOIN rented_agg ra ON ra.placa=s.placa AND ra.fecha=s.fecha;
"""

METRICS = """
SELECT
  COUNT(*)                                             AS placa_dias,
  SUM(rented_day)                                      AS rentados,
  ROUND(100.0*SUM(rented_day)/NULLIF(COUNT(*),0),1)    AS ocup_pct,
  ROUND(SUM(rev_usd)::numeric,0)                        AS rev_usd,
  SUM(CASE WHEN rentas_dia>1 THEN 1 ELSE 0 END)         AS pd_multi_contrato
FROM silver.{tbl}
WHERE EXTRACT(YEAR FROM fecha)=2026;
"""


def refresh_silver_fact(engine):
    print(">> Refrescando silver.fact_rental_vehicles desde bronze reparado ...")
    with engine.begin() as c:
        c.execute(text("DROP TABLE IF EXISTS silver.fact_rental_vehicles CASCADE"))
        c.execute(text("CREATE TABLE silver.fact_rental_vehicles AS "
                       "SELECT * FROM bronze.rent_shop_ra_fct_rental_vehicles_franchise"))
        c.execute(text("CREATE INDEX idx_fact_rental_vehicles_mvnr ON silver.fact_rental_vehicles(rntl_mvnr)"))
        c.execute(text("CREATE INDEX idx_fact_rental_vehicles_int_num ON silver.fact_rental_vehicles(vhcl_int_num)"))
        n = c.execute(text("SELECT COUNT(*) FROM silver.fact_rental_vehicles")).scalar()
    print(f"   silver.fact_rental_vehicles: {n:,} filas")


def snap(engine, tbl):
    return pd.read_sql(text(METRICS.format(tbl=tbl)), engine).iloc[0]


def main():
    t0 = time.time()
    engine = get_engine("silver,bronze")

    print(">> ANTES (tabla viva silver.gold_carro_dia, v3 header):")
    before = snap(engine, "gold_carro_dia")
    print(before.to_string())

    refresh_silver_fact(engine)

    print("\n>> Construyendo silver.gold_carro_dia__v4 (por segmento) ...")
    with engine.begin() as c:
        c.execute(text("SET LOCAL statement_timeout = 0"))
        c.execute(text("DROP TABLE IF EXISTS silver.gold_carro_dia__v4 CASCADE"))
        c.execute(text(V4_CREATE))
        c.execute(text("CREATE INDEX idx_gcd_v4_fecha ON silver.gold_carro_dia__v4(fecha)"))
        c.execute(text("CREATE INDEX idx_gcd_v4_sede ON silver.gold_carro_dia__v4(sede, fecha)"))
    print(f"   __v4 construida ({time.time()-t0:.0f}s)")

    print("\n>> DESPUES (silver.gold_carro_dia__v4, por segmento):")
    after = snap(engine, "gold_carro_dia__v4")
    print(after.to_string())

    print("\n" + "=" * 60)
    print("ANTES vs DESPUES (2026)")
    print("=" * 60)
    cmp = pd.DataFrame({"ANTES(v3)": before, "DESPUES(v4)": after})
    cmp["delta"] = cmp["DESPUES(v4)"] - cmp["ANTES(v3)"]
    print(cmp.to_string())

    # --- Controles del briefing ---
    print("\n>> CONTROLES")
    # LHL609 dias rentados 2026 (esperado ~26 en jun16-jul12; antes ~3)
    for tbl in ("gold_carro_dia", "gold_carro_dia__v4"):
        q = (f"SELECT SUM(rented_day) FROM silver.{tbl} "
             "WHERE placa='LHL609' AND fecha BETWEEN '2026-06-16' AND '2026-07-12'")
        v = pd.read_sql(text(q), engine).iloc[0, 0]
        print(f"   LHL609 dias rentados 16-jun a 12-jul ({tbl.split('__')[-1] if '__' in tbl else 'v3'}): {v}")
    # NLR239: no debe estar doble-reservada (rentas_dia>1) en v4 por header-bug
    for tbl in ("gold_carro_dia", "gold_carro_dia__v4"):
        q = (f"SELECT COUNT(*) FROM silver.{tbl} "
             "WHERE placa='NLR239' AND rentas_dia>1 AND EXTRACT(YEAR FROM fecha)=2026")
        v = pd.read_sql(text(q), engine).iloc[0, 0]
        print(f"   NLR239 placa-dias con >1 contrato 2026 ({tbl.split('__')[-1] if '__' in tbl else 'v3'}): {v}")

    # Bucaramanga julio: flota-dias/dias (control historico = 12)
    print("\n>> Bucaramanga julio 2026 (flota_prom = flota-dias/dias):")
    for tbl in ("gold_carro_dia", "gold_carro_dia__v4"):
        q = (f"SELECT ROUND(COUNT(*)::numeric/31,1) flota_prom, "
             f"COUNT(DISTINCT placa) placas, SUM(rented_day) rentados "
             f"FROM silver.{tbl} WHERE sede ILIKE '%BUCARAMANGA%' "
             "AND fecha BETWEEN '2026-07-01' AND '2026-07-31'")
        r = pd.read_sql(text(q), engine).iloc[0]
        tag = 'v4' if '__' in tbl else 'v3'
        print(f"   [{tag}] flota_prom={r['flota_prom']} placas_distintas={r['placas']} rentados={r['rentados']}")

    print(f"\n>> LISTO en {(time.time()-t0)/60:.1f} min. La tabla viva NO se toco.")


if __name__ == "__main__":
    main()
