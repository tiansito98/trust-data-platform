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
    xlsx_download_button,
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

# Limpieza del split prepay/counter en COP.
# Silver (vw_rentals_detail) tiene un bug: para algunos cargos prepagados,
# counter_cargo_cop reporta el subtotal_cop completo aunque counter_cargo_usd=0.
# Tambien hay ruido de TRM rounding (counter_cop ±$500 con counter_usd=0).
# USD tiene precision de cents y es source of truth: si counter_usd ~= 0,
# entonces counter_cop debe ser 0 y el monto va a prepagado.
_noise_mask = df["counter_usd"].abs() < 0.01
df.loc[_noise_mask, "prepagado_cop"] = df.loc[_noise_mask, "subtotal_cop"]
df.loc[_noise_mask, "prepagado_usd"] = df.loc[_noise_mask, "subtotal_usd"]
df.loc[_noise_mask, "counter_cop"] = 0.0
df.loc[_noise_mask, "counter_usd"] = 0.0

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
xlsx_download_button(
    bucket_summary,
    file_name=f"cargos_granular_bucket_{dt.date.today()}",
    sheet_name="Bucket COBRA",
    key="xlsx_cargos_bucket",
)


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
xlsx_download_button(
    code_summary,
    file_name=f"cargos_granular_codigos_{dt.date.today()}",
    sheet_name="Por codigo",
    key="xlsx_cargos_codigos",
)
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
    "Base comisionable = SUMA del counter (CON IVA 19%) SOLO para codigos "
    f"comisionables ({', '.join(COMISIONABLES)}) y SOLO cuando el cargo es "
    "100% counter (prepagado=0). "
    "Los MIXTOS (parte prepago + parte counter) NO cuentan porque el cargo "
    "ya venia de la reserva — el asesor solo proceso una extension, no lo "
    "vendio fresh. "
    "IVA incluido porque la comision se calcula sobre el monto CON IVA. "
    "Usa fecha de entrega (handover) del vehiculo. "
    "El codigo asesor corresponde a operador_handover_codigo en silver — "
    "proximamente se mapeara a nombre con una tabla de asesores."
)

# Regla comisionable: SOLO cargos PURE COUNTER de codigos comisionables.
# - PURE COUNTER = counter_usd > 0 AND prepagado_usd == 0 (no venia de reserva).
# - MIXTO (prepagado + counter) NO cuenta porque el cargo ya existia en reserva
#   y el asesor solo proceso una extension. No lo "vendio" fresh.
# - Threshold 0.01 USD para robustez ante ruido residual (aunque ya limpiamos).
is_pure_counter = (df["counter_usd"] > 0.01) & (df["prepagado_usd"] < 0.01)
df["es_base_comision"] = df["es_comisionable"] & is_pure_counter

df["counter_comisionable_usd"] = df["counter_usd"].where(df["es_base_comision"], 0.0)
df["counter_comisionable_cop"] = df["counter_cop"].where(df["es_base_comision"], 0.0)

asesor_summary = (
    df.groupby("asesor_codigo", dropna=False)
    .agg(
        contratos=("numero_contrato", "nunique"),
        cargos_counter=("counter_usd", lambda x: int((x > 0).sum())),
        # Comisionables (lo que realmente genera comision)
        base_comisionable_usd=("counter_comisionable_usd", "sum"),
        base_comisionable_cop=("counter_comisionable_cop", "sum"),
        # Counter total se usa internamente para % comisionable, no se muestra
        _counter_total_usd=("counter_usd", "sum"),
    )
    .reset_index()
    .sort_values("base_comisionable_usd", ascending=False)
)

# % comisionable = base comisionable / counter total (interno, no mostrado).
# Cast a float ANTES de dividir: las columnas vienen como Decimal de Postgres,
# y Decimal / pd.NA * 100 queda dtype object → .round(1) falla en pandas/3.14.
# .where(cond) mantiene float64 (NaN donde counter=0, no pd.NA).
# IMPORTANTE: pct se calcula ANTES de aplicar IVA a la base para que la ratio
# se mantenga (%) — de otro modo se inflaria 19%.
_base_f = pd.to_numeric(asesor_summary["base_comisionable_usd"], errors="coerce")
_cnt_f = pd.to_numeric(asesor_summary["_counter_total_usd"], errors="coerce")
asesor_summary["pct_comisionable"] = (
    (_base_f / _cnt_f.where(_cnt_f != 0)) * 100
).round(1)

# IVA (19%) sobre la base comisionable. La comision se calcula sobre el
# monto CON IVA (asi lo definio el negocio). Aplicamos DESPUES del pct para
# no distorsionarlo.
IVA_FACTOR_COMISION = 1.19
asesor_summary["base_comisionable_usd"] = (
    asesor_summary["base_comisionable_usd"] * IVA_FACTOR_COMISION
)
asesor_summary["base_comisionable_cop"] = (
    asesor_summary["base_comisionable_cop"] * IVA_FACTOR_COMISION
)

# Asesor "null" / sin codigo: ponemos string visible
asesor_summary["asesor_codigo"] = (
    asesor_summary["asesor_codigo"].fillna("(sin codigo)").astype(str)
)

# LEFT JOIN a operational.op_asesores para mostrar nombres.
# Si no hay match (asesor sin mapear todavia), muestra "-".
# La tabla puede o no existir; try/except para robustez.
try:
    _asesores_map = load_query(
        "SELECT codigo_silver, nombres, apellidos "
        "FROM operational.op_asesores "
        "WHERE codigo_silver IS NOT NULL"
    )
    if not _asesores_map.empty:
        _asesores_map["codigo_silver"] = (
            _asesores_map["codigo_silver"].astype("Int64").astype(str)
        )
        _asesores_map["nombre_completo"] = (
            _asesores_map["nombres"].fillna("") + " " +
            _asesores_map["apellidos"].fillna("")
        ).str.strip()
        # Normalizamos codigo_asesor a string para el merge
        asesor_summary["_codigo_num"] = (
            pd.to_numeric(asesor_summary["asesor_codigo"], errors="coerce")
            .astype("Int64").astype(str)
        )
        asesor_summary = asesor_summary.merge(
            _asesores_map[["codigo_silver", "nombre_completo"]],
            left_on="_codigo_num",
            right_on="codigo_silver",
            how="left",
        )
        asesor_summary = asesor_summary.drop(columns=["_codigo_num", "codigo_silver"])
    else:
        asesor_summary["nombre_completo"] = None
except Exception:
    asesor_summary["nombre_completo"] = None

asesor_summary["nombre_completo"] = (
    asesor_summary["nombre_completo"].fillna("(sin mapear)")
)

view_asesor = asesor_summary.copy()
view_asesor["base_comisionable_usd"] = view_asesor["base_comisionable_usd"].apply(
    lambda v: fmt_money(v, "USD")
)
view_asesor["base_comisionable_cop"] = view_asesor["base_comisionable_cop"].apply(
    lambda v: fmt_money(v, "COP")
)
view_asesor["pct_comisionable"] = view_asesor["pct_comisionable"].apply(
    lambda v: f"{v:.1f}%" if pd.notna(v) else "-"
)

# Solo mostramos columnas relevantes para comisiones
view_asesor = view_asesor[[
    "asesor_codigo", "nombre_completo", "contratos", "cargos_counter",
    "base_comisionable_usd", "base_comisionable_cop", "pct_comisionable",
]]

view_asesor = view_asesor.rename(columns={
    "asesor_codigo": "Codigo asesor",
    "nombre_completo": "Nombre",
    "contratos": "Contratos",
    "cargos_counter": "Cargos counter",
    "base_comisionable_usd": "BASE COMISIONABLE USD (c/IVA)",
    "base_comisionable_cop": "BASE COMISIONABLE COP (c/IVA)",
    "pct_comisionable": "% comisionable",
})
st.dataframe(view_asesor, use_container_width=True, hide_index=True)
xlsx_download_button(
    asesor_summary[[
        "asesor_codigo", "nombre_completo", "contratos", "cargos_counter",
        "base_comisionable_usd", "base_comisionable_cop", "pct_comisionable",
    ]],
    file_name=f"cargos_granular_asesor_{dt.date.today()}",
    sheet_name="Por asesor",
    key="xlsx_cargos_asesor",
)

# Total base comisionable (suma de todos los asesores) — sanity check
total_comisionable_usd = asesor_summary["base_comisionable_usd"].sum()
total_comisionable_cop = asesor_summary["base_comisionable_cop"].sum()

st.caption(
    f"Total base comisionable (suma de todos los asesores): "
    f"**{fmt_money(total_comisionable_usd, 'USD')}** / "
    f"**{fmt_money(total_comisionable_cop, 'COP')}**."
)


st.markdown("---")


# =============================================================================
# Seccion 3b: Drill-down por asesor — contratos con base comisionable
# =============================================================================
section("Drill-down: contratos con base comisionable por asesor")
st.caption(
    "Selecciona un asesor para ver los contratos y cargos exactos que "
    "aportan a su base comisionable. Solo aparecen cargos comisionables "
    f"({', '.join(COMISIONABLES)}) que fueron 100% counter (no MIXTO). "
    "Montos mostrados CON IVA 19%."
)

# Solo asesores que tienen algo en la base comisionable
_asesores_base = asesor_summary[
    pd.to_numeric(asesor_summary["base_comisionable_usd"], errors="coerce") > 0
].copy().sort_values("base_comisionable_usd", ascending=False)

if _asesores_base.empty:
    st.info("Ningun asesor tiene base comisionable en el periodo/sedes seleccionados.")
else:
    # Etiqueta: "Nombre (Codigo)" si esta mapeado, "Codigo — (sin mapear)" si no
    def _drill_label(row):
        codigo = row["asesor_codigo"]
        nombre = row["nombre_completo"]
        if nombre == "(sin mapear)":
            return f"{codigo} — (sin mapear)"
        return f"{nombre} ({codigo})"

    _asesores_base["_drill_label"] = _asesores_base.apply(_drill_label, axis=1)
    _options = ["-- Seleccionar asesor --"] + _asesores_base["_drill_label"].tolist()
    _selected = st.selectbox(
        "Asesor",
        options=_options,
        key="_drill_asesor_sel",
        help="Ordenados por base comisionable (mayor a menor).",
    )

    if _selected != "-- Seleccionar asesor --":
        # Extraer el codigo del selected
        _sel_row = _asesores_base[_asesores_base["_drill_label"] == _selected].iloc[0]
        _codigo_sel = _sel_row["asesor_codigo"]  # string
        _codigo_num = pd.to_numeric(_codigo_sel, errors="coerce")

        # Filtrar df a solo cargos de ese asesor que aportan a base
        _drill = df[
            (pd.to_numeric(df["asesor_codigo"], errors="coerce") == _codigo_num)
            & (df["es_base_comision"])
        ].copy()

        if _drill.empty:
            st.warning("No hay cargos base para este asesor en el periodo.")
        else:
            # Aplicar IVA (misma logica que la tabla de arriba)
            _drill["counter_ciiva_usd"] = _drill["counter_usd"] * IVA_FACTOR_COMISION
            _drill["counter_ciiva_cop"] = _drill["counter_cop"] * IVA_FACTOR_COMISION

            # Vista limpia
            _drill_view = _drill[[
                "numero_contrato", "fecha_entrega", "sede",
                "codigo", "descripcion",
                "counter_usd", "counter_ciiva_usd",
                "counter_cop", "counter_ciiva_cop",
            ]].copy()

            # Format money
            for c in ("counter_usd", "counter_ciiva_usd"):
                _drill_view[c] = _drill_view[c].apply(lambda v: fmt_money(v, "USD"))
            for c in ("counter_cop", "counter_ciiva_cop"):
                _drill_view[c] = _drill_view[c].apply(lambda v: fmt_money(v, "COP"))

            _drill_view = _drill_view.rename(columns={
                "numero_contrato": "Contrato",
                "fecha_entrega": "Entrega",
                "sede": "Sede",
                "codigo": "Cod",
                "descripcion": "Descripcion",
                "counter_usd": "Counter USD (s/IVA)",
                "counter_ciiva_usd": "Counter USD (c/IVA)",
                "counter_cop": "Counter COP (s/IVA)",
                "counter_ciiva_cop": "Counter COP (c/IVA)",
            })

            # Ordenar por contrato para agrupar visualmente
            _drill_view = _drill_view.sort_values(["Contrato", "Cod"])

            st.dataframe(_drill_view, use_container_width=True, hide_index=True)

            # Totales de este asesor
            _n_cargos = len(_drill)
            _n_contratos = _drill["numero_contrato"].nunique()
            _total_usd_ciiva = _drill["counter_ciiva_usd"].sum()
            _total_cop_ciiva = _drill["counter_ciiva_cop"].sum()

            st.caption(
                f"**{_n_cargos}** cargo(s) comisionable(s) en **{_n_contratos}** "
                f"contrato(s). "
                f"Base total: **{fmt_money(_total_usd_ciiva, 'USD')}** / "
                f"**{fmt_money(_total_cop_ciiva, 'COP')}** (c/IVA). "
                f"Este numero debe coincidir con la fila del asesor en la tabla "
                f"de arriba."
            )

            # Export
            xlsx_download_button(
                _drill[[
                    "numero_contrato", "fecha_entrega", "sede",
                    "codigo", "descripcion",
                    "counter_usd", "counter_ciiva_usd",
                    "counter_cop", "counter_ciiva_cop",
                ]],
                file_name=(
                    f"drill_asesor_{_codigo_sel}_{dt.date.today()}"
                ),
                sheet_name="Detalle base comision",
                key=f"xlsx_drill_asesor_{_codigo_sel}",
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
