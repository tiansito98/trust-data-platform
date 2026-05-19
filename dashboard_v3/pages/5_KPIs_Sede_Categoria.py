"""KPI ejecutivo por (anio, sede, categoria ACRISS).

Una fila por combinacion con: flota, ocupacion, tarifa promedio,
ingreso por unidad, ingreso total, reservas canceladas.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import plotly.express as px
from components.common import (
    inject_styles, render_header, section,
    load_query, year_filter,
    SIXT_ORANGE, SIXT_BLACK, PLOTLY_LAYOUT,
    fmt_int, fmt_pct, fmt_usd,
)

st.set_page_config(page_title="KPIs Sede + Categoria - Trust v3", layout="wide")
inject_styles()
render_header("KPIs por sede y categoria")

lo_year, hi_year = year_filter("Rango de años")

df = load_query(f"""
    SELECT *
    FROM vw_kpi_sede_categoria_anual
    WHERE anio BETWEEN {lo_year} AND {hi_year}
    ORDER BY anio DESC, sede, acriss
""")

if df.empty:
    st.warning("Sin datos en el rango.")
    st.stop()

# ---------- Filtros ----------

c1, c2, c3 = st.columns(3)
sedes = ["(Todas)"] + sorted(df["sede"].dropna().unique().tolist())
acriss_opts = ["(Todas)"] + sorted(df["acriss"].dropna().unique().tolist())
sede_sel = c1.selectbox("Sede", sedes)
acriss_sel = c2.selectbox("ACRISS", acriss_opts)
solo_con_flota = c3.checkbox("Solo filas con flota dominante > 0", value=True,
                             help="Excluye categorias servidas con carros 'prestados' de otra sede.")

fdf = df.copy()
if sede_sel != "(Todas)":
    fdf = fdf[fdf["sede"] == sede_sel]
if acriss_sel != "(Todas)":
    fdf = fdf[fdf["acriss"] == acriss_sel]
if solo_con_flota:
    fdf = fdf[fdf["flota"] > 0]

if fdf.empty:
    st.info("Sin datos para esa combinacion de filtros.")
    st.stop()

# ---------- Tabla principal ----------

section("Detalle por año + sede + categoria")

display = fdf.copy()
display["ocupacion_pct"] = display["ocupacion_pct"].map(fmt_pct)
for c in ("tarifa_promedio_dia_usd", "ingreso_total_usd", "ingreso_por_unidad_usd"):
    display[c] = display[c].map(fmt_usd)
for c in ("flota", "rentals", "dias_rentados", "dias_disponibles", "reservas_canceladas"):
    display[c] = display[c].map(fmt_int)

display = display.rename(columns={
    "anio": "Año",
    "sede": "Sede",
    "sede_codigo": "Cod sede",
    "acriss": "ACRISS",
    "flota": "Flota",
    "rentals": "Rentals",
    "dias_rentados": "Días rentados",
    "dias_disponibles": "Días disp.",
    "ocupacion_pct": "Ocupación",
    "tarifa_promedio_dia_usd": "Tarifa prom/día",
    "ingreso_total_usd": "Ingreso total",
    "ingreso_por_unidad_usd": "Ingreso/unidad",
    "reservas_canceladas": "Reservas canceladas",
}).drop(columns=["adicionales_usd", "tarifa_usd", "Cod sede"], errors="ignore")

st.dataframe(display, hide_index=True, use_container_width=True, height=520)

# ---------- Heatmap ingreso por unidad ----------

section(f"Ingreso por unidad (USD) - sede x ACRISS (promedio {lo_year}-{hi_year})")
pivot = fdf.groupby(["sede", "acriss"], as_index=False).agg(
    ingreso=("ingreso_total_usd", "sum"),
    flota=("flota", "sum"),
)
pivot["ingreso_por_unidad"] = (pivot["ingreso"] / pivot["flota"].replace(0, None)).round(0)
heat = pivot.pivot(index="sede", columns="acriss", values="ingreso_por_unidad")

fig = px.imshow(
    heat,
    color_continuous_scale=[[0, "#ffffff"], [1, SIXT_ORANGE]],
    aspect="auto",
    labels=dict(color="USD/unidad"),
    text_auto=".0f",
)
fig.update_layout(**PLOTLY_LAYOUT, height=440)
st.plotly_chart(fig, use_container_width=True)

# ---------- Heatmap ocupacion ----------

section(f"Ocupación % - sede x ACRISS (promedio {lo_year}-{hi_year})")
pivot_o = fdf.groupby(["sede", "acriss"], as_index=False).agg(
    dr=("dias_rentados", "sum"),
    dd=("dias_disponibles", "sum"),
)
pivot_o["ocupacion"] = (pivot_o["dr"] / pivot_o["dd"].replace(0, None) * 100).round(1)
heat_o = pivot_o.pivot(index="sede", columns="acriss", values="ocupacion")
fig2 = px.imshow(
    heat_o,
    color_continuous_scale=[[0, "#ffffff"], [0.5, "#f59e0b"], [1, "#2e7d32"]],
    aspect="auto",
    zmin=0, zmax=100,
    labels=dict(color="Ocupación %"),
    text_auto=".0f",
)
fig2.update_layout(**PLOTLY_LAYOUT, height=440)
st.plotly_chart(fig2, use_container_width=True)

with st.expander("Notas y limitaciones"):
    st.markdown(
        """
        - **Sede de un vehículo (flota)**: cada carro se asigna a su **sede
          dominante** del año (donde tuvo más handovers). Por eso la flota
          es un entero por (año, sede, ACRISS).
        - **Ocupación** = días rentados / días disponibles de la flota
          dominante. Los rentals se asignan a la sede del handover real, no
          a la sede dominante del carro. Si un carro dominante en Rionegro
          se rentó en Bogotá, esos días suman al numerador de Bogotá
          (handover real) pero el denominador de Bogotá no incluye ese
          carro → ocupación puede salir >100%. Activa el filtro "Solo filas
          con flota dominante > 0" para evitar el ruido.
        - **Tarifa promedio por día** = `tarifa (T) / días rentados`. No
          incluye adicionales.
        - **Ingreso por unidad** = `ingreso_total_usd / flota`. Mide cuánto
          generó cada vehículo en promedio en el año (síntoma de
          monetización del activo).
        - **Reservas canceladas** = `cancel_cliente + noshow_cliente +
          cancel_sixt` para esa misma (sede, ACRISS reservado, año).
        """
    )
