"""KPIs anuales: flota, ocupacion, revenue per day, tarifa, adicionales, total."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from components.common import (
    inject_styles, render_header, section, kpi,
    load_query, year_filter,
    SIXT_ORANGE, SIXT_BLACK, PLOTLY_LAYOUT,
    fmt_usd, fmt_int, fmt_pct,
)

st.set_page_config(page_title="KPIs Anuales - Trust v3", layout="wide")
inject_styles()
render_header("KPIs Anuales")

lo_year, hi_year = year_filter("Rango de años a mostrar")

df = load_query(f"""
    SELECT *
    FROM vw_kpi_anual
    WHERE anio BETWEEN {lo_year} AND {hi_year}
    ORDER BY anio
""")

if df.empty:
    st.warning("No hay data en el rango seleccionado.")
    st.stop()

# ---------- KPI cards (totales agregados del rango) ----------

totals = {
    "flota_max": df["flota_activa"].max(),
    "ocup_avg":  df["dias_rentados"].sum() / df["dias_disponibles"].sum() * 100 if df["dias_disponibles"].sum() else 0,
    "rpd_avg":   df["ingreso_total_usd"].sum() / df["dias_rentados"].sum() if df["dias_rentados"].sum() else 0,
    "rev_total": df["ingreso_total_usd"].sum(),
}

c1, c2, c3, c4 = st.columns(4)
kpi(c1, "Flota maxima en el rango",       fmt_int(totals["flota_max"]))
kpi(c2, "Ocupacion ponderada",            fmt_pct(totals["ocup_avg"]))
kpi(c3, "Revenue per day (promedio)",     fmt_usd(totals["rpd_avg"]))
kpi(c4, "Ingreso total (sin IVA)",        fmt_usd(totals["rev_total"]))

# ---------- Tabla anio por anio ----------

section("Detalle por año")

display = df.copy()
display["ocupacion_pct"] = display["ocupacion_pct"].map(lambda v: fmt_pct(v))
for c in ("tarifa_usd", "adicionales_usd", "descuento_usd", "ingreso_total_usd", "revenue_per_day_usd"):
    display[c] = display[c].map(fmt_usd)
for c in ("flota_activa", "dias_disponibles", "rentals", "dias_rentados"):
    display[c] = display[c].map(fmt_int)

st.dataframe(
    display.rename(columns={
        "anio": "Año",
        "flota_activa": "Flota activa",
        "dias_disponibles": "Dias disponibles",
        "rentals": "Rentals",
        "dias_rentados": "Dias rentados",
        "ocupacion_pct": "Ocupacion",
        "tarifa_usd": "Tarifa (T)",
        "adicionales_usd": "Adicionales",
        "descuento_usd": "Descuento",
        "ingreso_total_usd": "Ingreso total",
        "revenue_per_day_usd": "Revenue per day",
    }),
    hide_index=True, use_container_width=True,
)

# ---------- Charts ----------

section("Ocupacion vs flota")
fig = go.Figure()
fig.add_bar(
    x=df["anio"], y=df["flota_activa"], name="Flota activa",
    marker_color=SIXT_BLACK, yaxis="y2", opacity=0.4,
)
fig.add_scatter(
    x=df["anio"], y=df["ocupacion_pct"], name="Ocupacion %",
    mode="lines+markers", line=dict(color=SIXT_ORANGE, width=3),
    marker=dict(size=10),
)
fig.update_layout(
    **PLOTLY_LAYOUT,
    yaxis=dict(title="Ocupacion %", side="left"),
    yaxis2=dict(title="Flota activa", side="right", overlaying="y", showgrid=False),
    xaxis=dict(title="Año", dtick=1),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    height=380,
)
st.plotly_chart(fig, use_container_width=True)

section("Ingresos: tarifa vs adicionales (USD, sin IVA)")
fig2 = go.Figure()
fig2.add_bar(x=df["anio"], y=df["tarifa_usd"], name="Tarifa (T)", marker_color=SIXT_ORANGE)
fig2.add_bar(x=df["anio"], y=df["adicionales_usd"], name="Adicionales", marker_color=SIXT_BLACK)
fig2.update_layout(
    **PLOTLY_LAYOUT,
    barmode="stack",
    yaxis=dict(title="USD"),
    xaxis=dict(title="Año", dtick=1),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    height=380,
)
st.plotly_chart(fig2, use_container_width=True)

section("Revenue per day - evolucion")
fig3 = go.Figure()
fig3.add_scatter(
    x=df["anio"], y=df["revenue_per_day_usd"],
    mode="lines+markers+text",
    text=[fmt_usd(v) for v in df["revenue_per_day_usd"]],
    textposition="top center",
    line=dict(color=SIXT_ORANGE, width=3),
    marker=dict(size=12),
    name="RPD",
)
fig3.update_layout(
    **PLOTLY_LAYOUT,
    yaxis=dict(title="USD / dia rentado"),
    xaxis=dict(title="Año", dtick=1),
    height=320, showlegend=False,
)
st.plotly_chart(fig3, use_container_width=True)

with st.expander("Definiciones"):
    st.markdown(
        """
        - **Flota activa**: vehiculos distintos que estuvieron in-fleet en algun
          dia del año (basado en `vhcl_first_ci_date` y `vhcl_grounded_date`).
        - **Dias disponibles**: suma por vehiculo de los dias del año en que
          estuvo in-fleet.
        - **Ocupacion** = `dias_rentados` / `dias_disponibles`. Cuando un rental
          cruza el cambio de año, todos sus dias se asignan al anio del handover.
        - **Revenue per day** = `ingreso_total_usd` / `dias_rentados`.
        - **Ingreso total** = `neto_usd` (tarifa + adicionales - descuento, sin IVA).
        - **Adicionales** = todos los cargos counter del rental excepto `T`
          (Time and mileage).
        """
    )
