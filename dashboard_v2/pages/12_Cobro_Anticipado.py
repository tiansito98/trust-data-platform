"""
Cobro anticipado vs counter (USD) — solo trust_admin.

Para cada contrato: cuanto lo pago un TERCERO por adelantado (prepago web de Sixt,
mayorista con tarjeta corporativa, voucher de agencia) y la franquicia tiene que
reclamarlo despues, y cuanto se cobro en el COUNTER. Ej.: prepago de 200 USD y en el
counter se agregan 2 dias + conductor adicional por 100 -> 200 anticipado, 100 counter.

Toda la logica vive en silver.fact_cobro_contrato (build_cobro_contrato en
pipelines/silver/build.py); esta pagina solo filtra y suma. NO confundir con el
prepagado/counter de Cierre Diario: aquel dice si el cargo "venia en la reserva" (base
de las comisiones), no quien pago la plata.

Montos en USD con IVA (lo que efectivamente se paga). Filtra por fecha de ENTREGA del
contrato, igual que Cierre Diario.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import streamlit as st

from components.common import (
    inject_styles, render_header, section, kpi, fmt_money, fmt_int,
    load_query, xlsx_download_button,
)
from components.filters import render_sidebar_filters, render_active_filters_banner
from components.auth import require_auth, require_page, logout_button, get_current_user

st.set_page_config(page_title="TRUST - Cobro anticipado", layout="wide")
require_auth()
require_page("12_Cobro_Anticipado")
inject_styles()
logout_button()

# --- Gate: SOLO el perfil trust_admin ---
_u = get_current_user()
if not _u or _u.get("username") != "trust_admin":
    render_header("Cobro anticipado")
    st.warning("Solo el perfil **trust_admin** puede ver esta página.")
    st.stop()

render_header("Cobro anticipado vs counter (USD)")

filtros = render_sidebar_filters(default_days=30)
render_active_filters_banner(filtros)
if filtros.moneda != "USD":
    st.info("Esta vista es solo en **USD** (moneda de los contratos y de los prepagos).")

ORIGEN_NICE = {
    "PREPAGO_WEB_SIXT": "Prepago web (Sixt)",
    "MAYORISTA_TARJETA_CORPORATIVA": "Mayorista (tarjeta corporativa Sixt)",
    "VOUCHER_AGENCIA": "Voucher de agencia",
    "AGENCIA_PREPAGO": "Agencia (prepago)",
}

# =============================================================================
# Datos
# =============================================================================
_where = ["fecha_entrega BETWEEN :a AND :b"]
_params = {"a": filtros.fecha_desde.isoformat(), "b": filtros.fecha_hasta.isoformat()}
if filtros.sedes_codigos:
    _where.append("sede_handover_codigo = ANY(:sedes)")
    _params["sedes"] = [int(c) for c in filtros.sedes_codigos]
df = load_query(f"""
    SELECT numero_contrato, numero_reserva, fecha_entrega, fecha_devolucion, sede_handover,
           canal_cobro_tarifa, tipo_agencia_main, tercero_nombre, es_no_show, voucher_numero,
           pago_main_codigo, pago_main, pago_secondary_codigo, pago_secondary,
           prepago_reserva_usd, voucher_reserva_usd, main_usd, secondary_usd,
           total_usd, anticipado_usd, counter_usd, origen_anticipado, regla,
           revisar, motivo_revision
    FROM silver.fact_cobro_contrato
    WHERE {' AND '.join(_where)}
    ORDER BY fecha_entrega, numero_contrato
""", _params)
for c in ("total_usd", "anticipado_usd", "counter_usd", "main_usd", "secondary_usd",
          "prepago_reserva_usd", "voucher_reserva_usd"):
    df[c] = pd.to_numeric(df[c], errors="coerce")

if df.empty:
    st.info("No hay contratos en el rango seleccionado.")
    st.stop()

df["origen"] = df["origen_anticipado"].map(ORIGEN_NICE).fillna("Todo en counter")
df["a_quien"] = df.apply(
    lambda r: "Sixt (prepago web)" if r["origen_anticipado"] == "PREPAGO_WEB_SIXT"
    else (r["tercero_nombre"] or ORIGEN_NICE.get(r["origen_anticipado"], "-"))
    if r["anticipado_usd"] > 0 else "-", axis=1)
df["numero_contrato"] = df["numero_contrato"].astype("int64").astype(str)

ren = df[~df["es_no_show"]]
nos = df[df["es_no_show"]]

# =============================================================================
# KPIs (contratos; los no-shows van aparte)
# =============================================================================
_tot, _ant, _cnt = ren["total_usd"].sum(), ren["anticipado_usd"].sum(), ren["counter_usd"].sum()
k1, k2, k3, k4 = st.columns(4)
kpi(k1, "Contratos", fmt_int(len(ren)), f"{fmt_int(int((ren['anticipado_usd'] > 0).sum()))} con parte anticipada")
kpi(k2, "Total con IVA (USD)", fmt_money(_tot, "USD"), "igual a Cierre Diario")
kpi(k3, "Anticipado — a reclamar (USD)", fmt_money(_ant, "USD"),
    f"{_ant / _tot * 100:.1f}% del total" if _tot else "")
kpi(k4, "Cobrado en counter (USD)", fmt_money(_cnt, "USD"),
    f"{_cnt / _tot * 100:.1f}% del total" if _tot else "")
if len(nos):
    st.info(f"Además hay **{len(nos)} no-shows prepagados** por **{fmt_money(nos['anticipado_usd'].sum(), 'USD')}** "
            "anticipados: el cliente prepagó online, no se presentó y Sixt retuvo el prepago. "
            "No cuentan en los totales de arriba (Cierre Diario tampoco los cuenta); están al final.")

st.caption(
    "**Anticipado** = lo que pagó un tercero por adelantado: prepago web de Sixt (hasta lo "
    "prepagado), mayorista con tarjeta corporativa Sixt (CC) o voucher de agencia (hasta su "
    "valor). **Counter** = lo demás: lo que pagó el cliente en la sede (extras, días "
    "adicionales, reservas web con pago en counter). Montos con IVA, por fecha de entrega.")

# =============================================================================
# A quien reclamar
# =============================================================================
section("A quién reclamar")
_rec = (df[df["anticipado_usd"] > 0]
        .groupby(["origen", "a_quien"])
        .agg(contratos=("numero_contrato", "size"), anticipado=("anticipado_usd", "sum"))
        .reset_index().sort_values("anticipado", ascending=False))
st.dataframe(pd.DataFrame({
    "Origen": _rec["origen"].values,
    "A quién": _rec["a_quien"].values,
    "Contratos": _rec["contratos"].values,
    "Anticipado (USD)": _rec["anticipado"].map(lambda v: fmt_money(v, "USD")).values,
}), hide_index=True, use_container_width=True)
st.caption("Incluye los no-shows prepagados.")

# =============================================================================
# Contratos
# =============================================================================
section("Contratos")
_ver = st.radio("Mostrar", ["Todos", "Con parte anticipada", "Solo counter", "Para revisar"],
                horizontal=True, key="cobro_ver")
_t = ren
if _ver == "Con parte anticipada":
    _t = ren[ren["anticipado_usd"] > 0]
elif _ver == "Solo counter":
    _t = ren[ren["anticipado_usd"] == 0]
elif _ver == "Para revisar":
    _t = ren[ren["revisar"]]


def _tabla(t: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "Contrato": t["numero_contrato"].values,
        "Entrega": t["fecha_entrega"].values,
        "Sede": t["sede_handover"].values,
        "Origen anticipado": t["origen"].values,
        "A quién reclamar": t["a_quien"].values,
        "Pago main": t["pago_main_codigo"].fillna("").values,
        "Pago secondary": t["pago_secondary_codigo"].fillna("").values,
        "Total (USD)": t["total_usd"].round(2).values,
        "Anticipado (USD)": t["anticipado_usd"].round(2).values,
        "Counter (USD)": t["counter_usd"].round(2).values,
        "Regla": t["regla"].values,
        "Revisar": t["motivo_revision"].fillna("").values,
    })


_out = _tabla(_t)
st.dataframe(_out, hide_index=True, use_container_width=True,
             height=min(600, 38 + 35 * max(len(_out), 1)),
             column_config={c: st.column_config.NumberColumn(format="%.2f")
                            for c in ("Total (USD)", "Anticipado (USD)", "Counter (USD)")})
st.caption(f"{fmt_int(len(_out))} contratos · total {fmt_money(_t['total_usd'].sum(), 'USD')} · "
           f"anticipado {fmt_money(_t['anticipado_usd'].sum(), 'USD')} · "
           f"counter {fmt_money(_t['counter_usd'].sum(), 'USD')}")
xlsx_download_button(_tabla(df.assign(origen=df["origen"])).assign(
                         **{"No-show": df["es_no_show"].map({True: "Sí", False: ""}).values}),
                     file_name=f"cobro_anticipado_{filtros.fecha_desde}_{filtros.fecha_hasta}",
                     sheet_name="Contratos", key="cobro_xlsx")
st.caption("El Excel trae todos los contratos del rango (incluidos los no-shows prepagados).")

# =============================================================================
# Detalle de un contrato
# =============================================================================
section("Detalle de un contrato")
_sel = st.selectbox("Contrato", options=[""] + list(df["numero_contrato"]), key="cobro_det",
                    format_func=lambda x: "Elegí un contrato" if x == "" else x)
if _sel:
    r = df[df["numero_contrato"] == _sel].iloc[0]
    c1, c2, c3 = st.columns(3)
    kpi(c1, "Total (USD)", fmt_money(r["total_usd"], "USD"),
        f"main {fmt_money(r['main_usd'], 'USD')} + secondary {fmt_money(r['secondary_usd'], 'USD')}")
    kpi(c2, "Anticipado (USD)", fmt_money(r["anticipado_usd"], "USD"), r["a_quien"])
    kpi(c3, "Counter (USD)", fmt_money(r["counter_usd"], "USD"), r["regla"])
    _info = {
        "Pago main": f"{r['pago_main_codigo'] or '-'} ({r['pago_main'] or '-'})",
        "Pago secondary": f"{r['pago_secondary_codigo'] or '-'} ({r['pago_secondary'] or '-'})",
        "Prepago en la reserva (USD)": fmt_money(r["prepago_reserva_usd"], "USD") if pd.notna(r["prepago_reserva_usd"]) else "-",
        "Voucher en la reserva (USD)": fmt_money(r["voucher_reserva_usd"], "USD") if pd.notna(r["voucher_reserva_usd"]) else "-",
        "Número de voucher": r["voucher_numero"] or "-",
        "Reserva": str(int(r["numero_reserva"])) if pd.notna(r["numero_reserva"]) and r["numero_reserva"] else "-",
        "Canal / tipo de agencia": f"{r['canal_cobro_tarifa'] or '-'} / {r['tipo_agencia_main'] or '-'}",
    }
    if r["revisar"]:
        _info["Revisar"] = r["motivo_revision"]
    st.dataframe(pd.DataFrame({"Campo": list(_info.keys()), "Valor": list(_info.values())}),
                 hide_index=True, use_container_width=True)
    cargos = load_query("""
        SELECT cargo_codigo, cargo_descripcion, cargo_inty, cargo_periodo, cantidad,
               subtotal_con_iva_usd
        FROM silver.vw_rentals_detail
        WHERE numero_contrato = :c AND fuente_cargo = 'RENTAL_COUNTER'
        ORDER BY cargo_inty, cargo_posicion
    """, {"c": int(_sel)})
    if len(cargos):
        st.markdown("**Cargos del contrato** (main = cubo M, secondary = cubo S)")
        st.dataframe(pd.DataFrame({
            "Código": cargos["cargo_codigo"].values,
            "Descripción": cargos["cargo_descripcion"].values,
            "Cubo": cargos["cargo_inty"].map({"M": "Main", "S": "Secondary"}).fillna(cargos["cargo_inty"]).values,
            "Período": cargos["cargo_periodo"].values,
            "Cantidad": cargos["cantidad"].values,
            "Con IVA (USD)": pd.to_numeric(cargos["subtotal_con_iva_usd"], errors="coerce").round(2).values,
        }), hide_index=True, use_container_width=True)

# =============================================================================
# No-shows prepagados
# =============================================================================
if len(nos):
    section("No-shows prepagados")
    st.caption("Reservas prepagadas online donde el cliente no se presentó: Sixt cobró y "
               "retuvo el prepago. No son rentas (no tienen carro) y Cierre Diario no las "
               "cuenta, pero es plata reclamable.")
    st.dataframe(_tabla(nos), hide_index=True, use_container_width=True,
                 column_config={c: st.column_config.NumberColumn(format="%.2f")
                                for c in ("Total (USD)", "Anticipado (USD)", "Counter (USD)")})

st.caption("Fuente: silver.fact_cobro_contrato. Regla: el pagador MAIN/SECONDARY del contrato y "
           "su forma de pago (FE = counter; CC, FC, AI = tercero), más el prepago y el voucher de "
           "la reserva. Validado 2026: main + secondary = total en el 100% de los contratos.")
