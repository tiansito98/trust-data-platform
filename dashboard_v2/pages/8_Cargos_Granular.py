"""
Cargos Granular - solo admin (trust_admin).

Vista detallada de TODOS los cargos por periodo, organizada estilo COBRA:
  - Resumen por bucket (VENTAS / COBERTURAS / ADICIONALES / TAX)
  - Desglose por codigo individual de cargo (T, BF, LD, SL, Y, OT, OW, etc.)
  - Split counter vs prepagado (reserva) por cada cargo
  - Tabla de ventas por asesor (operador_handover_codigo) para calcular comisiones
    (solo cuenta lo cobrado en counter, no lo prepagado)

Si filtras por una fecha, el TOTAL NETO debe coincidir con el de Cierre Diario.
Las dos vistas usan los mismos filtros (fuente_cargo='RENTAL_COUNTER', USD).

Nota: las comisiones de los asesores se calculan sobre 'counter' porque el
prepagado ya fue cobrado por Sixt central (OTA, sixt.com.co) y no pasa por
las manos del asesor.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import datetime as dt

import pandas as pd
import streamlit as st

from components.auth import require_auth, require_page, is_admin, logout_button
from components.common import (
    inject_styles, render_header, section, kpi,
    fmt_money, load_query, render_trm_today_sidebar,
)


st.set_page_config(page_title="TRUST - Cargos Granular", layout="wide")
require_auth()
# Admin-only: require_page bloquea sede users via su pages list en users.yml.
# is_admin() es defensa extra por si algun sede llegara aqui.
require_page("8_Cargos_Granular")
if not is_admin():
    st.error("Esta pagina es solo para administradores (trust_admin).")
    st.stop()

inject_styles()
render_trm_today_sidebar()
logout_button()
render_header("Cargos Granular (Admin)")


# =============================================================================
# Filtros
# =============================================================================
section("Filtros")

# Default: ultimos 7 dias (incluyendo hoy)
default_end = dt.date.today()
default_start = default_end - dt.timedelta(days=6)

c1, c2, c3 = st.columns([1, 1, 2])
with c1:
    desde = st.date_input("Desde", value=default_start, key="cg_desde")
with c2:
    hasta = st.date_input("Hasta", value=default_end, key="cg_hasta")
with c3:
    # Cargar sedes para el multiselect
    sedes_df = load_query(
        "SELECT DISTINCT sede_handover AS sede "
        "FROM vw_rentals_resumen "
        "WHERE sede_handover IS NOT NULL "
        "ORDER BY sede_handover"
    )
    sedes_opts = sedes_df["sede"].tolist()
    sedes_sel = st.multiselect(
        "Sedes (opcional - todas si vacio)",
        options=sedes_opts,
        default=[],
        key="cg_sedes",
    )

if (hasta - desde).days < 0:
    st.error("La fecha 'Desde' no puede ser posterior a 'Hasta'.")
    st.stop()

if (hasta - desde).days > 90:
    st.warning(
        f"Rango de {(hasta - desde).days + 1} dias. Consultas grandes consumen "
        f"IO budget de Supabase. Considera reducir si no es necesario."
    )


# =============================================================================
# Query: cargar todos los cargos del periodo
# =============================================================================
sede_clause = ""
params = {"desde": desde, "hasta": hasta}
if sedes_sel:
    sede_clause = "AND sede_handover = ANY(:sedes)"
    params["sedes"] = list(sedes_sel)

charges_sql = f"""
    SELECT
        numero_contrato,
        sede_handover                       AS sede,
        fecha_handover_real::date           AS fecha_entrega,
        cargo_codigo                        AS codigo,
        cargo_descripcion                   AS descripcion,
        cargo_categoria                     AS categoria,
        CASE
            WHEN cargo_codigo = 'T'                THEN 'VENTAS'
            WHEN cargo_codigo IN ('BF','LD','SL')  THEN 'COBERTURAS'
            WHEN cargo_codigo = 'Y'                THEN 'TAX (Y)'
            ELSE                                        'ADICIONALES'
        END                                 AS bucket_cobra,
        canal_cobro_tarifa,
        operador_handover_codigo            AS asesor_codigo,
        operador_checkout_codigo            AS asesor_checkout,
        subtotal_usd,
        subtotal_cop,
        prepagado_cargo_usd                 AS prepagado_usd,
        counter_cargo_usd                   AS counter_usd,
        prepagado_cargo_cop                 AS prepagado_cop,
        counter_cargo_cop                   AS counter_cop
    FROM vw_rentals_detail
    WHERE fecha_handover_real::date BETWEEN :desde AND :hasta
      AND fuente_cargo = 'RENTAL_COUNTER'
      AND rental_currency = 'USD'
      AND TRIM(COALESCE(placa, '')) != ''
      {sede_clause}
"""
df = load_query(charges_sql, params)

if df.empty:
    st.info("No hay cargos en el periodo seleccionado.")
    st.stop()

# Convertir columnas numericas
num_cols = ["subtotal_usd", "subtotal_cop", "prepagado_usd",
            "counter_usd", "prepagado_cop", "counter_cop"]
for c in num_cols:
    df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)


# =============================================================================
# KPIs ejecutivos
# =============================================================================
section("Resumen")

total_contratos = df["numero_contrato"].nunique()
total_cargos = len(df)
total_neto_usd = df["subtotal_usd"].sum()
total_neto_cop = df["subtotal_cop"].sum()

k1, k2, k3, k4 = st.columns(4)
kpi(k1, "Contratos", f"{total_contratos:,}")
kpi(k2, "Cargos individuales", f"{total_cargos:,}")
kpi(k3, "Total neto USD", fmt_money(total_neto_usd, "USD"))
kpi(k4, "Total neto COP", fmt_money(total_neto_cop, "COP"))

st.caption(
    f"Periodo: {desde} → {hasta} ({(hasta - desde).days + 1} dias). "
    f"Total neto NO incluye IVA (es la base imponible suma de cargos counter). "
    f"Debe coincidir con la suma de Cierre Diario para el mismo periodo."
)


st.markdown("---")


# =============================================================================
# Seccion 1: Resumen por bucket COBRA (VENTAS / COBERTURAS / ADICIONALES / TAX)
# =============================================================================
section("Por bucket COBRA")
st.caption(
    "VENTAS=T (tarifa), COBERTURAS=BF+LD+SL, ADICIONALES=resto excepto Y, "
    "TAX=Y (location surcharge aeropuerto, NO es IVA)."
)

bucket_order = ["VENTAS", "COBERTURAS", "ADICIONALES", "TAX (Y)"]
bucket_summary = (
    df.groupby("bucket_cobra")
    .agg(
        counter_usd=("counter_usd", "sum"),
        prepagado_usd=("prepagado_usd", "sum"),
        total_usd=("subtotal_usd", "sum"),
        counter_cop=("counter_cop", "sum"),
        prepagado_cop=("prepagado_cop", "sum"),
        total_cop=("subtotal_cop", "sum"),
    )
    .reindex(bucket_order, fill_value=0)
    .reset_index()
)

# Fila TOTAL al final
total_row = pd.DataFrame([{
    "bucket_cobra": "TOTAL",
    "counter_usd": bucket_summary["counter_usd"].sum(),
    "prepagado_usd": bucket_summary["prepagado_usd"].sum(),
    "total_usd": bucket_summary["total_usd"].sum(),
    "counter_cop": bucket_summary["counter_cop"].sum(),
    "prepagado_cop": bucket_summary["prepagado_cop"].sum(),
    "total_cop": bucket_summary["total_cop"].sum(),
}])
bucket_summary = pd.concat([bucket_summary, total_row], ignore_index=True)

# Formato moneda
view = bucket_summary.copy()
for c in ("counter_usd", "prepagado_usd", "total_usd"):
    view[c] = view[c].apply(lambda v: fmt_money(v, "USD"))
for c in ("counter_cop", "prepagado_cop", "total_cop"):
    view[c] = view[c].apply(lambda v: fmt_money(v, "COP"))

view = view.rename(columns={
    "bucket_cobra": "Bucket",
    "counter_usd": "Counter USD",
    "prepagado_usd": "Prepagado USD",
    "total_usd": "Total USD",
    "counter_cop": "Counter COP",
    "prepagado_cop": "Prepagado COP",
    "total_cop": "Total COP",
})
st.dataframe(view, use_container_width=True, hide_index=True)


st.markdown("---")


# =============================================================================
# Seccion 2: Desglose por codigo de cargo individual
# =============================================================================
section("Por codigo de cargo")
st.caption(
    "Cada fila es un codigo unico (T, BF, LD, SL, Y, OT, OW, AD, FI, etc.). "
    "Counter = cobrado en mostrador. Prepagado = cobrado via OTA/Sixt central."
)

code_summary = (
    df.groupby(["bucket_cobra", "codigo", "descripcion"], dropna=False)
    .agg(
        contratos=("numero_contrato", "nunique"),
        cargos=("codigo", "count"),
        counter_usd=("counter_usd", "sum"),
        prepagado_usd=("prepagado_usd", "sum"),
        total_usd=("subtotal_usd", "sum"),
        counter_cop=("counter_cop", "sum"),
        prepagado_cop=("prepagado_cop", "sum"),
        total_cop=("subtotal_cop", "sum"),
    )
    .reset_index()
    .sort_values(["bucket_cobra", "total_usd"], ascending=[True, False])
)

view_codes = code_summary.copy()
for c in ("counter_usd", "prepagado_usd", "total_usd"):
    view_codes[c] = view_codes[c].apply(lambda v: fmt_money(v, "USD"))
for c in ("counter_cop", "prepagado_cop", "total_cop"):
    view_codes[c] = view_codes[c].apply(lambda v: fmt_money(v, "COP"))

view_codes = view_codes.rename(columns={
    "bucket_cobra": "Bucket",
    "codigo": "Codigo",
    "descripcion": "Descripcion",
    "contratos": "Contratos",
    "cargos": "Cargos",
    "counter_usd": "Counter USD",
    "prepagado_usd": "Prepagado USD",
    "total_usd": "Total USD",
    "counter_cop": "Counter COP",
    "prepagado_cop": "Prepagado COP",
    "total_cop": "Total COP",
})
st.dataframe(view_codes, use_container_width=True, hide_index=True)


st.markdown("---")


# =============================================================================
# Seccion 3: Ventas por asesor (handover) - base para comisiones
# =============================================================================
section("Ventas por asesor (codigo handover) — base de comisiones")
st.caption(
    "Solo cuenta lo cobrado en COUNTER (las comisiones no aplican a prepagado "
    "porque el cobro lo hace Sixt central, no el asesor). "
    "Usa fecha de entrega (handover) del vehiculo, no fecha de devolucion. "
    "El codigo de asesor corresponde a operador_handover_codigo en silver — "
    "proximamente se mapeara a nombre con una tabla de asesores."
)

asesor_summary = (
    df.groupby("asesor_codigo", dropna=False)
    .agg(
        contratos=("numero_contrato", "nunique"),
        cargos_counter=("counter_usd",
                        lambda x: int((x > 0).sum())),
        counter_usd=("counter_usd", "sum"),
        counter_cop=("counter_cop", "sum"),
        total_usd_atendido=("subtotal_usd", "sum"),
        total_cop_atendido=("subtotal_cop", "sum"),
    )
    .reset_index()
    .sort_values("counter_usd", ascending=False)
)

# Asesor "null" / sin codigo: ponemos string vacio
asesor_summary["asesor_codigo"] = asesor_summary["asesor_codigo"].fillna("(sin codigo)").astype(str)

view_asesor = asesor_summary.copy()
for c in ("counter_usd", "total_usd_atendido"):
    view_asesor[c] = view_asesor[c].apply(lambda v: fmt_money(v, "USD"))
for c in ("counter_cop", "total_cop_atendido"):
    view_asesor[c] = view_asesor[c].apply(lambda v: fmt_money(v, "COP"))

view_asesor = view_asesor.rename(columns={
    "asesor_codigo": "Codigo asesor",
    "contratos": "Contratos atendidos",
    "cargos_counter": "Cargos con counter",
    "counter_usd": "Counter USD (comisionable)",
    "counter_cop": "Counter COP (comisionable)",
    "total_usd_atendido": "Total USD atendido (info)",
    "total_cop_atendido": "Total COP atendido (info)",
})
st.dataframe(view_asesor, use_container_width=True, hide_index=True)

# Totales para sanity check
total_counter_usd = asesor_summary["counter_usd"].sum()
total_counter_cop = asesor_summary["counter_cop"].sum()
st.caption(
    f"Total counter (suma de todos los asesores): "
    f"{fmt_money(total_counter_usd, 'USD')} / {fmt_money(total_counter_cop, 'COP')}. "
    f"Debe coincidir con la columna 'Counter' de la fila TOTAL del bucket COBRA arriba."
)


st.markdown("---")


# =============================================================================
# Seccion 4: Descargar data raw
# =============================================================================
section("Exportar")

csv_data = df.to_csv(index=False).encode("utf-8")
st.download_button(
    label=f"Descargar CSV ({len(df):,} cargos)",
    data=csv_data,
    file_name=f"cargos_granular_{desde}_{hasta}.csv",
    mime="text/csv",
)
