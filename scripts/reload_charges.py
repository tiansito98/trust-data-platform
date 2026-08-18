"""
reload_charges.py - Repara las tablas de charges corruptas por la PK gruesa.

Contexto: el upsert incremental usaba PK (resn,konr) / (mvnr,konr), que borraba
el grupo entero de cargos de una reserva/contrato cuando Sixt actualizaba solo un
subconjunto -> se perdian cargos (ej. coberturas prepagadas que silver mandaba a
counter). La PK ya se corrigio en tables.yml; esto REPARA la data historica.

Pasos:
  1. Full reload de ch_fct_ra_charges + ch_fct_rs_charges desde Redshift (espejo exacto).
  2. Silver rebuild (refresca fact_charges + recalcula el split prepago/counter).
  3. Valida 4 contratos: las coberturas/adicionales prepagadas deben salir PREPAGO.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pipelines._common import get_engine, open_redshift        # noqa: E402
from pipelines.bronze.incremental import refresh_table, load_tables_config  # noqa: E402
from pipelines.silver import build                              # noqa: E402
from sqlalchemy import text                                     # noqa: E402
import pandas as pd                                             # noqa: E402

CHARGE_TARGETS = [
    "rent_shop_ch_fct_ra_charges_franchise",
    "rent_shop_ch_fct_rs_charges_franchise",
]
CONTRATOS = (9523780438, 9523826009, 9523854089, 9523876772)


def main():
    t0 = time.time()

    print(">> 1. FULL RELOAD de charges desde Redshift (espejo exacto) ...")
    cfgs = [t for t in load_tables_config() if t["target"] in CHARGE_TARGETS]
    if len(cfgs) != 2:
        raise RuntimeError(f"Esperaba 2 tablas de charges, encontre {len(cfgs)}")
    engine = get_engine("bronze")
    with open_redshift() as rs_conn:
        for cfg in cfgs:
            cfg = dict(cfg)
            cfg["mode"] = "full"        # fuerza full reload (DROP + recarga completa)
            target, ok = refresh_table(rs_conn, engine, cfg)
            print(f"   {target}: {'OK' if ok else 'FAIL'}")
            if not ok:
                raise RuntimeError(f"Fallo el reload de {target}")

    print("\n>> 2. SILVER REBUILD (recalcula split prepago/counter) ...")
    build.main()

    print("\n>> 3. VALIDACION - coberturas/adicionales de los 4 contratos")
    e = get_engine("silver,bronze")
    q = """
        SELECT numero_contrato AS contrato, cargo_codigo AS cod,
               cargo_categoria AS categoria, fuente_cargo AS fuente,
               cargo_coincide_reserva AS coincide,
               ROUND(prepagado_cargo_usd::numeric, 2) AS prepagado,
               ROUND(counter_cargo_usd::numeric, 2)   AS counter
        FROM silver.vw_rentals_detail
        WHERE numero_contrato IN (9523780438, 9523826009, 9523854089, 9523876772)
          AND cargo_categoria IN ('COBERTURA', 'EXTRA', 'OTROS')
        ORDER BY numero_contrato, cargo_codigo
    """
    with pd.option_context("display.width", 200, "display.max_rows", 80):
        print(pd.read_sql(text(q), e).to_string(index=False))

    print(f"\n>> LISTO en {(time.time() - t0) / 60:.1f} min. "
          "Las coberturas prepagadas (SL/BF/LD...) deben mostrar prepagado > 0.")


if __name__ == "__main__":
    main()
