"""
Cargos Granular - admin (historico completo) y usuarios de sede (su sede, desde agosto 2026).

Vista detallada de TODOS los cargos por periodo, organizada estilo COBRA:
  - Resumen por bucket (VENTAS / COBERTURAS / ADICIONALES / TAX)
  - Desglose por codigo individual de cargo (T, BF, LD, SL, Y, OT, OW, etc.)
  - Split counter vs prepagado (reserva) por cada cargo
  - Tabla de ventas por asesor (operador_handover_codigo = quien APERTURA el
    contrato) para calcular comisiones (solo cuenta lo cobrado en counter, no
    lo prepagado)

Acceso: admin ve todo. Los usuarios de sede ven solo su sede y solo desde
FECHA_MINIMA_SEDE (agosto 2026) en adelante.

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
#   BS = silla / booster
#   UP = upgrade de categoria
#   CS = child seat
#   BC = road assistance
#   PF = Protection Fee (muy raro: 2 contratos en 2026)
#   SL = liability
#
# NO COMISIONAN (decision de negocio, 2026-08-26): OT y FI.
# Se evaluaron en la auditoria de comisiones de julio 2026 y quedaron fuera
# de forma explicita. No agregarlos sin aprobacion del area comercial.
COMISIONABLES = ["AD", "BF", "LD", "BS", "UP", "CS", "BC", "PF", "SL"]
NO_COMISIONABLES_EXPLICITO = ["OT", "FI"]

# Piso de fecha para usuarios de sede. Antes de esta fecha los datos de
# comisiones estaban mal atribuidos (ver auditoria julio 2026), asi que solo
# trust_admin puede consultarlos.
FECHA_MINIMA_SEDE = dt.date(2026, 8, 1)

from components.auth import require_auth, require_page, is_admin, logout_button
from components.common import (
    inject_styles, render_header, section, kpi,
    fmt_money, load_query, render_trm_today_sidebar,
    xlsx_download_button,
)


st.set_page_config(page_title="TRUST - Cargos Granular", layout="wide")
require_auth()
# Acceso por pages list en users.yml. Sede: solo su sede y desde agosto 2026.
# ES_ADMIN decide el piso de fecha y el alcance de sedes mas abajo.
require_page("8_Cargos_Granular")

# Solo el admin (trust_admin) ve el calendario completo. Para todos los demas
# el date_input arranca en FECHA_MINIMA_SEDE.
ES_ADMIN = is_admin()
PISO_FECHA = None if ES_ADMIN else FECHA_MINIMA_SEDE

inject_styles()
logout_button()
render_header("Cargos Granular" if ES_ADMIN else "Cargos Granular (tu sede)")
if not ES_ADMIN:
    st.caption(
        f"Datos disponibles desde el {FECHA_MINIMA_SEDE.strftime('%d/%m/%Y')}. "
        "Los periodos anteriores estan en revision y solo los consulta "
        "administracion."
    )


# =============================================================================
# Filtros — sidebar unificado (mismo que Cierre Diario, Ingresos, Vehiculos)
# =============================================================================
from components.filters import render_sidebar_filters, render_active_filters_banner  # noqa: E402

filtros = render_sidebar_filters(default_days=7, min_fecha=PISO_FECHA)
render_active_filters_banner(filtros)

desde = filtros.fecha_desde
hasta = filtros.fecha_hasta
sedes_sel = filtros.sedes_codigos  # ahora usa CODIGOS de sede, no nombres

if (hasta - desde).days < 0:
    st.error("La fecha 'Desde' no puede ser posterior a 'Hasta'.")
    st.stop()

# Guardarrail: el calendario ya arranca en FECHA_MINIMA_SEDE para los no-admin,
# asi que esto no deberia dispararse nunca. Queda por si el rango llega por otra
# via (session_state viejo, cambio futuro en el sidebar).
if not ES_ADMIN and desde < FECHA_MINIMA_SEDE:
    desde = FECHA_MINIMA_SEDE

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
sede_clause_comision = ""  # para silver.fact_comision_dia (sin alias de tabla)
params = {"desde": desde, "hasta": hasta}

# Un usuario de sede SIEMPRE debe quedar filtrado. Si su sede no resolvio a un
# codigo, la clausula quedaria vacia y veria toda la compania: cortamos antes.
if not ES_ADMIN and not sedes_sel:
    st.error("No pudimos resolver tu sede. Contacta a administracion.")
    st.stop()

if sedes_sel:
    # Ahora usamos CODIGO de sede (int) — consistente con Cierre Diario/Ingresos/etc.
    sede_clause_detail = "AND d.sede_handover_codigo = ANY(:sedes)"
    sede_clause_resumen = "AND r.sede_handover_codigo = ANY(:sedes)"
    sede_clause_comision = "AND sede_handover_codigo = ANY(:sedes)"
    params["sedes"] = list(sedes_sel)

# Query 1: cargos individuales desde vw_rentals_detail
# Filtros MATCH EXACTO con Cierre Diario:
#   - fecha_handover_real::date BETWEEN
#   - fuente_cargo = 'RENTAL_COUNTER'
#   - rental_currency = 'USD'
# NO filtramos por TRIM(placa)!='' porque Cierre Diario no lo hace
# (incluye contratos shadow de status-match, que aportan $0 pero existen).
#
# COP: computamos USD * TRM Banrep (dim_trm_diaria) por fila para cuadrar
# con Cierre Diario. Los campos _cop nativos de silver usan TRM interna
# Sixt y quedaban ~1.3% distintos del NETO de Cierre Diario.
charges_sql = f"""
    SELECT
        d.numero_contrato,
        d.sede_handover                       AS sede,
        d.fecha_handover_real::date           AS fecha_entrega,
        d.cargo_codigo                        AS codigo,
        d.cargo_descripcion                   AS descripcion,
        d.cargo_categoria                     AS categoria,
        CASE
            WHEN d.cargo_codigo = 'T'                THEN 'VENTAS'
            WHEN d.cargo_codigo IN ('BF','LD','SL')  THEN 'COBERTURAS'
            WHEN d.cargo_codigo = 'Y'                THEN 'TAX (Y)'
            ELSE                                          'ADICIONALES'
        END                                    AS bucket_cobra,
        d.canal_cobro_tarifa,
        d.cargo_periodo                        AS periodo,
        d.operador_handover_codigo             AS asesor_codigo,
        d.operador_devolucion_codigo           AS asesor_devolucion,
        d.subtotal_usd,
        ROUND(d.subtotal_usd::numeric * t.trm_cop_per_usd, 0)         AS subtotal_cop,
        d.prepagado_cargo_usd                  AS prepagado_usd,
        d.counter_cargo_usd                    AS counter_usd,
        ROUND(d.prepagado_cargo_usd::numeric * t.trm_cop_per_usd, 0)  AS prepagado_cop,
        ROUND(d.counter_cargo_usd::numeric * t.trm_cop_per_usd, 0)    AS counter_cop
    FROM vw_rentals_detail d
    LEFT JOIN dim_trm_diaria t
           ON t.fecha = d.fecha_handover_real::date
    WHERE d.fecha_handover_real::date BETWEEN :desde AND :hasta
      AND d.fuente_cargo = 'RENTAL_COUNTER'
      AND d.rental_currency = 'USD'
      -- Excluir no-shows y cancelaciones (contratos sin placa o total 0)
      AND TRIM(COALESCE(d.placa, '')) <> ''
      AND COALESCE(d.subtotal_usd, 0) > 0
      {sede_clause_detail}
"""
df = load_query(charges_sql, params)

if df.empty:
    st.info("No hay cargos en el periodo seleccionado.")
    st.stop()

# Convertir columnas numericas
num_cols = ["subtotal_usd", "subtotal_cop", "prepagado_usd",
            "counter_usd", "prepagado_cop", "counter_cop", "periodo"]
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
# COP: computamos USD * TRM Banrep (dim_trm_diaria) por fila para cuadrar
# con Cierre Diario (regla del repo: siempre TRM Banrep, no la interna Sixt).
totales_sql = f"""
    SELECT
        COUNT(*)                                          AS contratos,
        COALESCE(SUM(r.bruto_usd), 0)                     AS bruto_usd,
        COALESCE(SUM(r.descuento_usd), 0)                 AS descuento_usd,
        COALESCE(SUM(r.neto_usd), 0)                      AS neto_usd,
        COALESCE(SUM(r.iva_usd), 0)                       AS iva_usd,
        COALESCE(SUM(r.total_con_iva_usd), 0)             AS total_con_iva_usd,
        COALESCE(SUM(ROUND(r.bruto_usd::numeric         * t.trm_cop_per_usd, 0)), 0) AS bruto_cop,
        COALESCE(SUM(ROUND(r.descuento_usd::numeric     * t.trm_cop_per_usd, 0)), 0) AS descuento_cop,
        COALESCE(SUM(ROUND(r.neto_usd::numeric           * t.trm_cop_per_usd, 0)), 0) AS neto_cop,
        COALESCE(SUM(ROUND(r.iva_usd::numeric            * t.trm_cop_per_usd, 0)), 0) AS iva_cop,
        COALESCE(SUM(ROUND(r.total_con_iva_usd::numeric  * t.trm_cop_per_usd, 0)), 0) AS total_con_iva_cop
    FROM vw_rentals_resumen r
    LEFT JOIN dim_trm_diaria t
           ON t.fecha = r.fecha_handover_real::date
    WHERE r.fecha_handover_real::date BETWEEN :desde AND :hasta
      AND r.rental_currency = 'USD'
      -- Excluir no-shows y cancelaciones (sin placa o total 0)
      AND TRIM(COALESCE(r.placa, '')) <> ''
      AND COALESCE(r.total_con_iva_usd, 0) > 0
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
    "Tampoco cuentan las EXTENSIONES: si a un contrato se le hace una "
    "modificacion que lo alarga, Sixt republica los mismos adicionales en un "
    "periodo nuevo. Ese cargo se arrastra solo, el asesor no lo vuelve a "
    "vender, y por eso solo comisiona el primer periodo (el ingreso si cuenta "
    "completo). "
    "IVA incluido porque la comision se calcula sobre el monto CON IVA. "
    "La comision del asesor = 5% de esa base. "
    "**PRORRATEO POR DIA:** la base se reparte por dia efectivo 24h del contrato, "
    "asi que una renta que cruza meses aporta a cada mes SOLO sus dias (ej. renta "
    "del 25-jun al 4-jul: junio 6/10, julio 4/10). Al filtrar un rango ves solo la "
    "porcion de esos dias. Atribuida al asesor que ENTREGO/abrio el contrato. "
    "Columnas 'Dias ocupacion' y 'Dias renta' reflejan actividad del asesor "
    "en el rango de fechas seleccionado arriba."
)

# Metas de dias renta 24h POR SEDE.
# Cada sede tiene su propia meta (senior/junior/tamano de flota difieren).
# Default 500 dias por sede; el usuario ajusta cada una segun corresponda.
SEDES_CONOCIDAS = [
    "BOGOTA EL DORADO INTL AIRPORT",
    "MEDELLIN AP JOSE MARIA CORDOVA",
    "MEDELLIN CITY EL POBLADO",
    "PEREIRA AIRPORT MATECANA INTL",
    "BUCARAMANGA AIRPORT",
    "SANTA MARTA SIMON BOLIVAR",
]
DEFAULT_META_SEDE = 500  # Ajustable por sede en la UI

with st.expander("Metas de dias renta 24h (por sede)", expanded=False):
    st.caption(
        "Ajusta la meta mensual de dias renta 24h por sede. Los valores "
        "se mantienen mientras dure la sesion. Un contrato de 25h "
        "cuenta como 2 dias (bloques de 24h clipped al rango)."
    )
    meta_por_sede = {}
    meta_cols_ui = st.columns(3)
    for idx, sede in enumerate(SEDES_CONOCIDAS):
        with meta_cols_ui[idx % 3]:
            # Etiqueta corta para no romper layout
            sede_short = sede.replace(" INTL AIRPORT", "").replace(
                " AP JOSE MARIA CORDOVA", " AP"
            ).replace(" AIRPORT MATECANA INTL", "").replace(
                " SIMON BOLIVAR", ""
            ).replace(" CITY", "").replace(" EL DORADO", "")
            meta_por_sede[sede] = st.number_input(
                f"Meta {sede_short}",
                min_value=0, max_value=10000, value=DEFAULT_META_SEDE, step=50,
                key=f"_cargos_meta_{sede}",
            )

# Meta global = suma de metas por sede (para KPI de total)
meta_dias = sum(meta_por_sede.values()) if meta_por_sede else 0

# Regla comisionable: SOLO cargos PURE COUNTER, de codigos comisionables, y del
# PRIMER periodo del contrato.
# - PURE COUNTER = counter_usd > 0 AND prepagado_usd == 0 (no venia de reserva).
# - MIXTO (prepagado + counter) NO cuenta porque el cargo ya existia en reserva
#   y el asesor solo proceso una extension. No lo "vendio" fresh.
# - PERIODO 0 = venta original. Cuando a un contrato se le hace una modificacion
#   que lo extiende, Sixt republica los mismos cargos con periodo 1, 2, ... El
#   adicional se arrastra solo, el asesor no lo vuelve a vender, y por eso la
#   extension no comisiona. Sigue contando como ingreso. (Regla confirmada con
#   la manager el 2026-08-26 sobre el contrato 9523788459, extendido del 31-jul
#   al 31-ago: solo comisiona el primer BF.)
# - Threshold 0.01 USD para robustez ante ruido residual (aunque ya limpiamos).
is_pure_counter = (df["counter_usd"] > 0.01) & (df["prepagado_usd"] < 0.01)
es_primer_periodo = df["periodo"].fillna(0) == 0
df["es_base_comision"] = df["es_comisionable"] & is_pure_counter & es_primer_periodo

df["counter_comisionable_usd"] = df["counter_usd"].where(df["es_base_comision"], 0.0)
df["counter_comisionable_cop"] = df["counter_cop"].where(df["es_base_comision"], 0.0)

# Base comisionable PRORRATEADA por dia efectivo (silver.fact_comision_dia).
# Cada renta aporta SOLO sus dias dentro de la ventana [desde,hasta]: una renta
# que cruza meses ya NO cuenta completa en el mes de entrega, sino que reparte
# su base por dia (regla 24h). La base viene YA con IVA y en COP a TRM Banrep
# del dia de entrega. Atribuida al operador de handover. Los flags es_base_comision
# de df siguen alimentando las secciones 1-2 (cargos/codigos por entrega).
comision_sql = f"""
    SELECT operador_handover_codigo         AS asesor_codigo,
           COUNT(DISTINCT numero_contrato)  AS contratos,
           SUM(base_comision_usd_civa_dia)  AS base_comisionable_usd,
           SUM(base_comision_cop_civa_dia)  AS base_comisionable_cop
    FROM silver.fact_comision_dia
    WHERE fecha BETWEEN :desde AND :hasta
      {sede_clause_comision}
    GROUP BY 1
"""
asesor_summary = load_query(comision_sql, params)
if asesor_summary.empty:
    asesor_summary = pd.DataFrame(
        columns=["asesor_codigo", "contratos",
                 "base_comisionable_usd", "base_comisionable_cop"]
    )
# Codigo a entero-string limpio (Postgres lo devuelve como float: 7798873.0).
asesor_summary["asesor_codigo"] = (
    pd.to_numeric(asesor_summary["asesor_codigo"], errors="coerce")
    .astype("Int64").astype(str).replace("<NA>", "(sin codigo)")
)
for _c in ("base_comisionable_usd", "base_comisionable_cop", "contratos"):
    asesor_summary[_c] = pd.to_numeric(asesor_summary[_c], errors="coerce").fillna(0)
asesor_summary = asesor_summary.sort_values("base_comisionable_usd", ascending=False)

# Dias por SEDE (ocupacion + renta 24h) para el rango [desde, hasta].
# - dias_ocupacion: metrica acida (COUNT DISTINCT placa+fecha) expandiendo
#   cada contrato a carro-dia CLIPPED al rango.
# - dias_renta_24h: bloques de 24h REALES clipped al rango (usa timestamps
#   hora_handover / hora_devolucion, no solo fechas). Ejemplo: contrato de
#   25h cuenta como 2 dias, no 2 dias calendario.
dias_sql_sede = f"""
    WITH rentas AS (
        SELECT
            r.numero_contrato, r.placa,
            r.sede_handover,
            r.fecha_handover_real::date AS f_ini,
            LEAST(
                COALESCE(r.fecha_devolucion_real::date, CURRENT_DATE),
                CURRENT_DATE
            ) AS f_fin,
            f.hora_handover, f.hora_devolucion
        FROM silver.vw_rentals_resumen r
        LEFT JOIN silver.vw_rentals_full f
               ON f.numero_contrato = r.numero_contrato
        WHERE r.rental_currency = 'USD'
          AND TRIM(COALESCE(r.placa, '')) <> ''
          AND r.fecha_handover_real IS NOT NULL
          AND f.hora_handover IS NOT NULL
          AND r.fecha_handover_real::date <= CURRENT_DATE
          -- Overlap con rango [desde, hasta]:
          AND r.fecha_handover_real::date <= :hasta
          AND LEAST(COALESCE(r.fecha_devolucion_real::date, CURRENT_DATE),
                    CURRENT_DATE) >= :desde
          {sede_clause_resumen}
    ),
    -- Metrica A: expandir a carro-dia clipped al rango
    carro_dia AS (
        SELECT
            r.sede_handover, r.placa, gs::date AS fecha
        FROM rentas r
        CROSS JOIN LATERAL generate_series(
            GREATEST(r.f_ini, CAST(:desde AS date)),
            LEAST(r.f_fin, CAST(:hasta AS date)),
            INTERVAL '1 day'
        ) gs
    ),
    ocupacion AS (
        SELECT sede_handover,
               COUNT(DISTINCT placa || '~' || fecha::text) AS dias_ocupacion
        FROM carro_dia
        GROUP BY sede_handover
    ),
    -- Metrica B: dias 24h clipped a rango via timestamps
    renta_24h AS (
        SELECT
            sede_handover,
            SUM(
                GREATEST(
                    CEIL(
                        EXTRACT(EPOCH FROM (
                            LEAST(
                                COALESCE(hora_devolucion, CURRENT_TIMESTAMP),
                                CURRENT_TIMESTAMP,
                                (CAST(:hasta AS date) + INTERVAL '1 day')::timestamp
                            )
                            - GREATEST(hora_handover, CAST(:desde AS date)::timestamp)
                        )) / 86400.0
                    )::int,
                    1
                )
            ) AS dias_renta_24h,
            COUNT(*) AS contratos
        FROM rentas
        GROUP BY sede_handover
    )
    SELECT
        COALESCE(o.sede_handover, r.sede_handover) AS sede,
        COALESCE(o.dias_ocupacion, 0)              AS dias_ocupacion,
        COALESCE(r.dias_renta_24h, 0)              AS dias_renta_24h,
        COALESCE(r.contratos, 0)                   AS contratos
    FROM ocupacion o
    FULL OUTER JOIN renta_24h r ON r.sede_handover = o.sede_handover
    ORDER BY dias_renta_24h DESC
"""
df_dias_sede = load_query(dias_sql_sede, params)
if not df_dias_sede.empty:
    for c in ("dias_ocupacion", "dias_renta_24h", "contratos"):
        df_dias_sede[c] = pd.to_numeric(
            df_dias_sede[c], errors="coerce"
        ).fillna(0).astype(int)

total_dias_ocupacion = int(df_dias_sede["dias_ocupacion"].sum()) if not df_dias_sede.empty else 0
total_dias_renta_24h = int(df_dias_sede["dias_renta_24h"].sum()) if not df_dias_sede.empty else 0
pct_meta_global = (
    round((total_dias_renta_24h / meta_dias) * 100, 1)
    if meta_dias > 0 else 0.0
)

# La base de fact_comision_dia YA viene con IVA 19% (no re-aplicar). La comision
# del asesor = 5% de esa base con IVA (asi lo definio el negocio, hard rule 13).
IVA_FACTOR_COMISION = 1.19  # se conserva por si alguna seccion lo referencia
TASA_COMISION = 0.05
asesor_summary["comision_usd"] = asesor_summary["base_comisionable_usd"] * TASA_COMISION
asesor_summary["comision_cop"] = asesor_summary["base_comisionable_cop"] * TASA_COMISION

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

# ---------- KPIs de dias (TOTAL del periodo + sede filtrada) ----------
kpi_c1, kpi_c2, kpi_c3 = st.columns(3)
kpi(kpi_c1, "Dias ocupacion (total)", f"{total_dias_ocupacion:,}")
kpi(kpi_c2, "Dias renta 24h (total)", f"{total_dias_renta_24h:,}")
kpi(
    kpi_c3,
    f"% Cumplimiento meta ({meta_dias:,} dias)",
    f"{pct_meta_global:.1f}%",
)

# Tabla de breakdown por sede — cada sede tiene su propia meta
if not df_dias_sede.empty and len(df_dias_sede) > 0:
    _sede_view = df_dias_sede.copy()
    # Meta especifica por sede (viene del dict meta_por_sede)
    _sede_view["meta"] = _sede_view["sede"].map(meta_por_sede).fillna(0).astype(int)
    _sede_view["pct_meta_num"] = _sede_view.apply(
        lambda r: (r["dias_renta_24h"] / r["meta"] * 100) if r["meta"] > 0 else 0.0,
        axis=1,
    ).round(1)
    _sede_view["pct_meta"] = _sede_view["pct_meta_num"].apply(lambda v: f"{v:.1f}%")
    _sede_view = _sede_view[[
        "sede", "contratos", "dias_ocupacion", "dias_renta_24h", "meta", "pct_meta"
    ]].rename(columns={
        "sede": "Sede",
        "contratos": "Contratos",
        "dias_ocupacion": "Dias ocupacion",
        "dias_renta_24h": "Dias renta 24h",
        "meta": "Meta",
        "pct_meta": "% Cumplimiento",
    })
    st.markdown("**Breakdown por sede (con meta especifica):**")
    st.dataframe(_sede_view, use_container_width=True, hide_index=True)

# ---------- Tabla por asesor (comisiones prorrateadas del periodo) ----------
view_asesor = asesor_summary.copy()
view_asesor["contratos"] = pd.to_numeric(
    view_asesor["contratos"], errors="coerce").fillna(0).astype(int)
for _c, _cur in (("base_comisionable_usd", "USD"), ("comision_usd", "USD"),
                 ("base_comisionable_cop", "COP"), ("comision_cop", "COP")):
    view_asesor[_c] = view_asesor[_c].apply(lambda v, cur=_cur: fmt_money(v, cur))

view_asesor = view_asesor[[
    "asesor_codigo", "nombre_completo", "contratos",
    "base_comisionable_cop", "comision_cop",
    "base_comisionable_usd", "comision_usd",
]].rename(columns={
    "asesor_codigo": "Codigo asesor",
    "nombre_completo": "Nombre",
    "contratos": "Contratos",
    "base_comisionable_cop": "BASE COMISIONABLE COP (c/IVA)",
    "comision_cop": "COMISION COP (5%)",
    "base_comisionable_usd": "BASE COMISIONABLE USD (c/IVA)",
    "comision_usd": "COMISION USD (5%)",
})
st.dataframe(view_asesor, use_container_width=True, hide_index=True)
xlsx_download_button(
    asesor_summary[[
        "asesor_codigo", "nombre_completo", "contratos",
        "base_comisionable_cop", "comision_cop",
        "base_comisionable_usd", "comision_usd",
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
    "Selecciona un asesor para ver los contratos que aportan a su base "
    "comisionable en la ventana, con el PRORRATEO por dia. 'Dias (ventana / "
    "total)' muestra cuantos dias efectivos del contrato caen en el rango vs "
    "el total del contrato; la base mostrada es solo la porcion de esos dias "
    "(CON IVA 19%). La suma coincide con la fila del asesor de arriba."
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
        _sel_row = _asesores_base[_asesores_base["_drill_label"] == _selected].iloc[0]
        _codigo_sel = _sel_row["asesor_codigo"]  # string
        _cod_raw = pd.to_numeric(_codigo_sel, errors="coerce")

        if pd.isna(_cod_raw):
            st.info("Asesor sin codigo mapeado; no hay drill por contrato.")
        else:
            # Contratos del asesor con su PRORRATEO dentro de la ventana.
            _drill_sql = f"""
                SELECT numero_contrato,
                       MAX(sede_handover)              AS sede,
                       MIN(n_dias)                     AS dias_totales,
                       COUNT(*)                        AS dias_en_ventana,
                       SUM(base_comision_usd_civa_dia) AS base_usd,
                       SUM(base_comision_cop_civa_dia) AS base_cop
                FROM silver.fact_comision_dia
                WHERE fecha BETWEEN :desde AND :hasta
                  AND operador_handover_codigo = :cod
                  {sede_clause_comision}
                GROUP BY numero_contrato
                ORDER BY base_cop DESC
            """
            _drill = load_query(_drill_sql, dict(params, cod=int(_cod_raw)))

            if _drill.empty:
                st.warning("No hay contratos con base comisionable para este asesor en la ventana.")
            else:
                for _c in ("base_usd", "base_cop", "dias_totales", "dias_en_ventana"):
                    _drill[_c] = pd.to_numeric(_drill[_c], errors="coerce").fillna(0)
                _drill["comision_cop"] = _drill["base_cop"] * TASA_COMISION
                _tot_usd = float(_drill["base_usd"].sum())
                _tot_cop = float(_drill["base_cop"].sum())
                _n_contratos = int(_drill["numero_contrato"].nunique())

                _dv = _drill.copy()
                _dv["Contrato"] = pd.to_numeric(
                    _dv["numero_contrato"], errors="coerce").astype("Int64").astype(str)
                _dv["Dias (ventana / total)"] = (
                    _dv["dias_en_ventana"].astype(int).astype(str) + " / "
                    + _dv["dias_totales"].astype(int).astype(str))
                _dv["Base prorrateada COP (c/IVA)"] = _dv["base_cop"].apply(lambda v: fmt_money(v, "COP"))
                _dv["Comision COP (5%)"] = _dv["comision_cop"].apply(lambda v: fmt_money(v, "COP"))
                _dv["Base prorrateada USD (c/IVA)"] = _dv["base_usd"].apply(lambda v: fmt_money(v, "USD"))
                _dv = _dv[[
                    "Contrato", "sede", "Dias (ventana / total)",
                    "Base prorrateada COP (c/IVA)", "Comision COP (5%)",
                    "Base prorrateada USD (c/IVA)",
                ]].rename(columns={"sede": "Sede"})
                st.dataframe(_dv, use_container_width=True, hide_index=True)

                st.caption(
                    f"**{_n_contratos}** contrato(s) con dias en la ventana. "
                    f"Base prorrateada total: **{fmt_money(_tot_usd, 'USD')}** / "
                    f"**{fmt_money(_tot_cop, 'COP')}** (c/IVA). "
                    f"Coincide con la fila del asesor de arriba."
                )

                xlsx_download_button(
                    _drill[[
                        "numero_contrato", "sede", "dias_en_ventana", "dias_totales",
                        "base_cop", "comision_cop", "base_usd",
                    ]],
                    file_name=f"drill_asesor_{_codigo_sel}_{dt.date.today()}",
                    sheet_name="Prorrateo por contrato",
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
