"""
reload_rental_vehicles.py - Repara ra_fct_rental_vehicles por la PK gruesa.

Contexto (2026-08-30): el grano real de rent_shop.ra_fct_rental_vehicles es
(rntl_mvnr, vhcl_int_num, rvnc_hser) -> 1 fila por SEGMENTO de un contrato. Un
contrato puede cambiar de carro a mitad de renta, y una MISMA placa puede
reasignarse dos veces en el mismo contrato. La PK del upsert era
(rntl_mvnr, vhcl_int_num) sin rvnc_hser, asi que el DELETE-INSERT colapsaba los
segmentos de una placa repetida y sobrevivia uno solo. Misma familia del bug de
PK de charges (fix agosto 2026).

Alcance medido en Redshift: 36 pares colisionados, 38 filas perdidas en el
historico (3 en 2024, 13 en 2025, 15 en 2026).

La PK ya se corrigio en config/tables.yml; esto REPARA la data historica con un
FULL RELOAD de esa unica tabla (espejo exacto de Redshift). IO despreciable
(~17k filas). NO reconstruye silver (eso es el PASO 2).

Validacion (cifras de control):
  - Contrato 9523555919 debe traer 4 segmentos (hser 0=NLR239, 1=LHL609,
    2=LHL602, 3=LHL609). Antes del fix trae 3 (falta el hser=1 de LHL609).
  - LHL609 (vhcl_int_num 15801353) debe aparecer en 2 segmentos de ese contrato.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pipelines._common import get_engine, open_redshift        # noqa: E402
from pipelines.bronze.incremental import refresh_table, load_tables_config  # noqa: E402
from sqlalchemy import text                                     # noqa: E402
import pandas as pd                                             # noqa: E402

TARGET = "rent_shop_ra_fct_rental_vehicles_franchise"
CONTRATO_CTRL = 9523555919
LHL609_INT = 15801353


def main():
    t0 = time.time()
    engine = get_engine("bronze")

    # Conteo previo (para ver cuantas filas recupera el reload).
    with engine.begin() as c:
        antes = c.execute(text(f"SELECT COUNT(*) FROM bronze.{TARGET}")).scalar()
    print(f">> Filas en bronze.{TARGET} ANTES del reload: {antes:,}")

    print("\n>> 1. FULL RELOAD desde Redshift (espejo exacto) ...")
    cfgs = [t for t in load_tables_config() if t["target"] == TARGET]
    if len(cfgs) != 1:
        raise RuntimeError(f"Esperaba 1 config para {TARGET}, encontre {len(cfgs)}")
    cfg = dict(cfgs[0])
    cfg["mode"] = "full"        # DROP + recarga completa
    assert cfg["pk"] == ["rntl_mvnr", "vhcl_int_num", "rvnc_hser"], \
        f"La PK en tables.yml no incluye rvnc_hser: {cfg['pk']}"
    with open_redshift() as rs_conn:
        target, ok = refresh_table(rs_conn, engine, cfg)
        print(f"   {target}: {'OK' if ok else 'FAIL'}")
        if not ok:
            raise RuntimeError(f"Fallo el reload de {target}")

    with engine.begin() as c:
        despues = c.execute(text(f"SELECT COUNT(*) FROM bronze.{TARGET}")).scalar()
    print(f"\n>> Filas DESPUES: {despues:,}  (delta {despues - antes:+,})")

    print("\n>> 2. VALIDACION - segmentos del contrato de control 9523555919")
    e = get_engine("bronze")
    q = f"""
        SELECT v.rntl_mvnr, v.rvnc_hser, v.vhcl_int_num, d.vhcl_plate AS placa,
               v.rvnc_handover_datm::date AS entrega,
               v.rvnc_return_datm::date   AS devolucion,
               v.rvnc_rental_days         AS dias,
               v.rvnc_handover_mileage    AS km_ini,
               v.rvnc_return_mileage      AS km_fin
        FROM bronze.{TARGET} v
        LEFT JOIN (SELECT DISTINCT ON (vhcl_int_num) vhcl_int_num, vhcl_plate
                   FROM bronze.fleet_shop_ve_dim_vehicles) d USING (vhcl_int_num)
        WHERE v.mndt_code = 409 AND v.rntl_mvnr = {CONTRATO_CTRL}
        ORDER BY v.rvnc_hser
    """
    df = pd.read_sql(text(q), e)
    with pd.option_context("display.width", 200, "display.max_rows", 40):
        print(df.to_string(index=False))

    n_seg = len(df)
    n_lhl = int((df["vhcl_int_num"] == LHL609_INT).sum()) if not df.empty else 0
    print(f"\n>> Segmentos del contrato {CONTRATO_CTRL}: {n_seg} (esperado 4)")
    print(f">> Segmentos de LHL609 (int {LHL609_INT}) en ese contrato: {n_lhl} (esperado 2)")
    ok_ctrl = (n_seg == 4 and n_lhl == 2)
    print(f">> CONTROL: {'OK - bronze reparado' if ok_ctrl else 'REVISAR - no cuadra'}")

    print(f"\n>> LISTO en {(time.time() - t0) / 60:.1f} min. "
          "Siguiente: PASO 2 (silver/gold usan el timeline por segmento).")
    return 0 if ok_ctrl else 1


if __name__ == "__main__":
    sys.exit(main())
