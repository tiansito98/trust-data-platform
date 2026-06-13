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


# Codigos de cargo que generan comision al asesor.
# Solo aplica la porcion COUNTER de estos cargos (lo prepagado ya lo cobro
# Sixt central y no genera comision local).
#   AD = conductor adicional
#   BF = full cover
#   LD = LDW (Loss Damage Waiver)
#   BS = ?
#   UP = upgrade de categoria
#   CS = child seat
#   BC = road assistance
#   PF = ? (posiblemente Protection Fee — aun no aparece, pero se incluye)
#   SL = liability
COMISIONABLES = ["AD", "BF", "LD", "BS", "UP", "CS", "BC", "PF", "SL"]

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
sede_clause_detail = ""
sede_clause_resumen = ""
params = {"desde": desde, "hasta": hasta}
if sedes_sel:
    sede_clause_detail = "AND sede_handover = ANY(:sedes)"
    sede_clause_resumen = "AND sede_handover = ANY(:sedes)"
    params["sedes"] = list(sedes_sel)

# Query 1: cargos individuales desde vw_rentals_detail
# Filtros MATCH EXACTO con Cierre Diario:
#   - fecha_handover_real::date BETWEEN
#   - fuente_cargo = 'RENTAL_COUNTER'
#   - rental_currency = 'USD'
# NO filtramos por TRIM(placa)!='' porque Cierre Diario no lo hace
# (incluye contratos shadow de status-match, que aportan $0 pero existen).
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
      {sede_clause_detail}
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

# Flag de comisionable: cargo cuyo counter aporta a la base de comision del asesor
df["es_comisionable"] = df["codigo"].isin(COMISIONABLES)

# Query 2: totales (bruto, descuento, neto) desde vw_rentals_resumen
# Estos son los MISMOS numeros que muestra Cierre Diario en sus KPIs.
# Necesitamos descuento_usd/cop porque en detail solo tenemos subtotal (bruto).
totales_sql = f"""
    SELECT
        COUNT(*)                                AS contratos,
        COALESCE(SUM(bruto_usd), 0)             AS bruto_usd,
        COALESCE(SUM(descuento_usd), 0)         AS descuento_usd,
        COALESCE(SUM(neto_usd), 0)              AS neto_usd,
        COALESCE(SUM(iva_usd), 0)               AS iva_usd,
        COALESCE(SUM(total_con_iva_usd), 0)     AS total_con_iva_usd,
        COALESCE(SUM(bruto_cop), 0)             AS bruto_cop,
        COALESCE(SUM(descuento_cop), 0)         AS descuento_cop,
        COALESCE(SUM(neto_cop), 0)              AS neto_cop,
        COALESCE(SUM(iva_cop), 0)               AS iva_cop,
        COALESCE(SUM(total_con_iva_cop), 0)     AS total_con_iva_cop
    FROM vw_rentals_resumen
    WHERE fecha_handover_real::date BETWEEN :desde AND :hasta
      AND rental_currency = 'USD'
      {sede_clause_resumen}
"""
df_tot = load_query(totales_sql, params)
totales = df_tot.iloc[0]


# =============================================================================
# KPIs ejecutivos (vienen de vw_rentals_resumen — mismos que Cierre Diario)
# =============================================================================
section("Resumen")

contratos_resumen = int(totales["contratos"])
total_cargos = len(df)

k1, k2, k3, k4 = st.columns(4)
kpi(k1, "Contratos", f"{contratos_resumen:,}")
kpi(k2, "Cargos individuales", f"{total_cargos:,}")
kpi(k3, "Neto USD (=Cierre Diario)", fmt_money(float(totales["neto_usd"]), "USD"))
kpi(k4, "Neto COP (=Cierre Diario)", fmt_money(float(totales["neto_cop"]), "COP"))

st.caption(
    f"Periodo: {desde} → {hasta} ({(hasta - desde).days + 1} dias). "
    f"Contratos y Neto vienen de vw_rentals_resumen (mismo source que Cierre "
    f"Diario). Neto = Bruto - Descuento, antes de IVA."
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

# Filas finales: SUBTOTAL BRUTO (cargos) + DESCUENTO + TOTAL NETO (=Cierre Diario)
subtotal_row = pd.DataFrame([{
    "bucket_cobra": "SUBTOTAL BRUTO (cargos)",
    "counter_usd": bucket_summary["counter_usd"].sum(),
    "prepagado_usd": bucket_summary["prepagado_usd"].sum(),
    "total_usd": bucket_summary["total_usd"].sum(),
    "counter_cop": bucket_summary["counter_cop"].sum(),
    "prepagado_cop": bucket_summary["prepagado_cop"].sum(),
    "total_cop": bucket_summary["total_cop"].sum(),
}])

descuento_row = pd.DataFrame([{
    "bucket_cobra": "(-) DESCUENTO",
    "counter_usd": 0.0,
    "prepagado_usd": 0.0,
    "total_usd": -float(totales["descuento_usd"]),
    "counter_cop": 0.0,
    "prepagado_cop": 0.0,
    "total_cop": -float(totales["descuento_cop"]),
}])

neto_row = pd.DataFrame([{
    "bucket_cobra": "TOTAL NETO (=Cierre Diario)",
    "counter_usd": 0.0,
    "prepagado_usd": 0.0,
    "total_usd": float(totales["neto_usd"]),
    "counter_cop": 0.0,
    "prepagado_cop": 0.0,
    "total_cop": float(totales["neto_cop"]),
}])

bucket_summary = pd.concat(
    [bucket_summary, subtotal_row, descuento_row, neto_row],
    ignore_index=True,
)

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

# Flag de comision al nivel de codigo
code_summary["comision"] = code_summary["codigo"].apply(
    lambda c: "Si" if c in COMISIONABLES else ""
)

view_codes = code_summary.copy()
for c in ("counter_usd", "prepagado_usd", "total_usd"):
    view_codes[c] = view_codes[c].apply(lambda v: fmt_money(v, "USD"))
for c in ("counter_cop", "prepagado_cop", "total_cop"):
    view_codes[c] = view_codes[c].apply(lambda v: fmt_money(v, "COP"))

# Reordenar para poner "Comision" al lado de "Codigo"
view_codes = view_codes[[
    "bucket_cobra", "codigo", "comision", "descripcion", "contratos", "cargos",
    "counter_usd", "prepagado_usd", "total_usd",
    "counter_cop", "prepagado_cop", "total_cop",
]]

view_codes = view_codes.rename(columns={
    "bucket_cobra": "Bucket",
    "codigo": "Codigo",
    "comision": "Comision?",
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
st.caption(
    f"Codigos que generan comision (counter solamente): "
    f"{', '.join(COMISIONABLES)}"
)


st.markdown("---")


# =============================================================================
# Seccion 3: Ventas por asesor (handover) - base para comisiones
# =============================================================================
section("Ventas por asesor (codigo handover) — base de comisiones")
st.caption(
    "Base comisionable = SUMA del counter SOLO para codigos comisionables "
    f"({', '.join(COMISIONABLES)}). "
    "El resto del counter (tarifa T, location Y, otros adicionales) NO genera "
    "comision para el asesor. "
    "Usa fecha de entrega (handover) del vehiculo. "
    "El codigo asesor corresponde a operador_handover_codigo en silver — "
    "proximamente se mapeara a nombre con una tabla de asesores."
)

# Calcular counter del cargo SOLO si es comisionable, sino 0
df["counter_comisionable_usd"] = df.apply(
    lambda r: r["counter_usd"] if r["es_comisionable"] else 0.0,
    axis=1,
)
df["counter_comisionable_cop"] = df.apply(
    lambda r: r["counter_cop"] if r["es_comisionable"] else 0.0,
    axis=1,
)

asesor_summary = (
    df.groupby("asesor_codigo", dropna=False)
    .agg(
        contratos=("numero_contrato", "nunique"),
        cargos_counter=("counter_usd", lambda x: int((x > 0).sum())),
        # Comisionables (lo que realmente genera comision)
        base_comisionable_usd=("counter_comisionable_usd", "sum"),
        base_comisionable_cop=("counter_comisionable_cop", "sum"),
        # Counter total (info — para ver cuanto del total counter es comisionable)
        counter_total_usd=("counter_usd", "sum"),
        counter_total_cop=("counter_cop", "sum"),
        # Atendido total (info)
        total_usd_atendido=("subtotal_usd", "sum"),
        total_cop_atendido=("subtotal_cop", "sum"),
    )
    .reset_index()
    .sort_values("base_comisionable_usd", ascending=False)
)

# % comisionable del counter total
asesor_summary["pct_comisionable"] = (
    asesor_summary["base_comisionable_usd"]
    / asesor_summary["counter_total_usd"].replace(0, pd.NA) * 100
).round(1)

# Asesor "null" / sin codigo: ponemos string visible
asesor_summary["asesor_codigo"] = (
    asesor_summary["asesor_codigo"].fillna("(sin codigo)").astype(str)
)

view_asesor = asesor_summary.copy()
for c in ("base_comisionable_usd", "counter_total_usd", "total_usd_atendido"):
    view_asesor[c] = view_asesor[c].apply(lambda v: fmt_money(v, "USD"))
for c in ("base_comisionable_cop", "counter_total_cop", "total_cop_atendido"):
    view_asesor[c] = view_asesor[c].apply(lambda v: fmt_money(v, "COP"))
view_asesor["pct_comisionable"] = view_asesor["pct_comisionable"].apply(
    lambda v: f"{v:.1f}%" if pd.notna(v) else "-"
)

# Reordenar: lo mas importante (base comisionable) primero
view_asesor = view_asesor[[
    "asesor_codigo", "contratos", "cargos_counter",
    "base_comisionable_usd", "base_comisionable_cop", "pct_comisionable",
    "counter_total_usd", "counter_total_cop",
    "total_usd_atendido", "total_cop_atendido",
]]

view_asesor = view_asesor.rename(columns={
    "asesor_codigo": "Codigo asesor",
    "contratos": "Contratos",
    "cargos_counter": "Cargos counter",
    "base_comisionable_usd": "BASE COMISIONABLE USD",
    "base_comisionable_cop": "BASE COMISIONABLE COP",
    "pct_comisionable": "% comisionable",
    "counter_total_usd": "Counter total USD",
    "counter_total_cop": "Counter total COP",
    "total_usd_atendido": "Total USD atendido",
    "total_cop_atendido": "Total COP atendido",
})
st.dataframe(view_asesor, use_container_width=True, hide_index=True)

# Totales para sanity check
total_comisionable_usd = asesor_summary["base_comisionable_usd"].sum()
total_comisionable_cop = asesor_summary["base_comisionable_cop"].sum()
total_counter_usd = asesor_summary["counter_total_usd"].sum()
total_counter_cop = asesor_summary["counter_total_cop"].sum()

st.caption(
    f"Total base comisionable (suma de todos los asesores): "
    f"**{fmt_money(total_comisionable_usd, 'USD')}** / "
    f"**{fmt_money(total_comisionable_cop, 'COP')}**. "
    f"Total counter (todos los codigos): {fmt_money(total_counter_usd, 'USD')} / "
    f"{fmt_money(total_counter_cop, 'COP')}."
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
