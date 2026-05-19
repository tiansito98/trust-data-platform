"""Demanda: % served y cancel rate desagregado (cliente / no-show / Sixt)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import plotly.graph_objects as go
from components.common import (
    inject_styles, render_header, section, kpi,
    load_query, year_filter,
    SIXT_ORANGE, SIXT_BLACK, PLOTLY_LAYOUT,
    fmt_int, fmt_pct,
)

st.set_page_config(page_title="Demanda - Trust v3", layout="wide")
inject_styles()
render_header("Demanda")

lo_year, hi_year = year_filter("Rango de años a mostrar")

df = load_query(f"""
    SELECT *
    FROM vw_demanda_anual
    WHERE anio BETWEEN {lo_year} AND {hi_year}
    ORDER BY anio
""")

if df.empty:
    st.warning("No hay data en el rango.")
    st.stop()

# ---------- KPIs ponderados ----------

total_res = df["total_reservas"].sum()
total_served = df["served"].sum()
total_cancel_cliente = df["cancel_cliente"].sum()
total_noshow = df["noshow_cliente"].sum()
total_cancel_sixt = df["cancel_sixt"].sum()

c1, c2, c3, c4 = st.columns(4)
kpi(c1, "Reservas totales (rango)", fmt_int(total_res))
kpi(c2, "% served ponderado",       fmt_pct(total_served / total_res * 100) if total_res else "-")
kpi(c3, "% cancel cliente",         fmt_pct(total_cancel_cliente / total_res * 100) if total_res else "-")
kpi(c4, "% no-show + cancel Sixt",  fmt_pct((total_noshow + total_cancel_sixt) / total_res * 100) if total_res else "-")

# ---------- Tabla ----------

section("Detalle por año")

display = df.copy()
for c in ("served", "cancel_cliente", "noshow_cliente", "cancel_sixt", "total_reservas"):
    display[c] = display[c].map(fmt_int)
for c in ("served_pct", "cancel_rate_pct", "cancel_cliente_pct", "noshow_cliente_pct", "cancel_sixt_pct"):
    display[c] = display[c].map(fmt_pct)

st.dataframe(
    display.rename(columns={
        "anio": "Año",
        "served": "Served",
        "cancel_cliente": "Cancel cliente",
        "noshow_cliente": "No-show cliente",
        "cancel_sixt": "Cancel Sixt",
        "total_reservas": "Total",
        "served_pct": "% served",
        "cancel_rate_pct": "% cancel rate",
        "cancel_cliente_pct": "% cancel cliente",
        "noshow_cliente_pct": "% no-show cliente",
        "cancel_sixt_pct": "% cancel Sixt",
    }),
    hide_index=True, use_container_width=True,
)

# ---------- Stacked breakdown ----------

section("Composición de la demanda (por año)")
fig = go.Figure()
fig.add_bar(x=df["anio"], y=df["served"],           name="Served",          marker_color=SIXT_ORANGE)
fig.add_bar(x=df["anio"], y=df["cancel_cliente"],   name="Cancel cliente",  marker_color="#666666")
fig.add_bar(x=df["anio"], y=df["noshow_cliente"],   name="No-show cliente", marker_color="#999999")
fig.add_bar(x=df["anio"], y=df["cancel_sixt"],      name="Cancel Sixt",     marker_color=SIXT_BLACK)
fig.update_layout(
    **PLOTLY_LAYOUT,
    barmode="stack",
    yaxis=dict(title="Reservas"),
    xaxis=dict(title="Año", dtick=1),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    height=420,
)
st.plotly_chart(fig, use_container_width=True)

# ---------- % series ----------

section("% por categoría (evolución)")
fig2 = go.Figure()
fig2.add_scatter(x=df["anio"], y=df["served_pct"],          name="% served",          mode="lines+markers", line=dict(color=SIXT_ORANGE, width=3))
fig2.add_scatter(x=df["anio"], y=df["cancel_cliente_pct"],  name="% cancel cliente",  mode="lines+markers", line=dict(color="#666666"))
fig2.add_scatter(x=df["anio"], y=df["noshow_cliente_pct"],  name="% no-show cliente", mode="lines+markers", line=dict(color="#999999"))
fig2.add_scatter(x=df["anio"], y=df["cancel_sixt_pct"],     name="% cancel Sixt",     mode="lines+markers", line=dict(color=SIXT_BLACK))
fig2.update_layout(
    **PLOTLY_LAYOUT,
    yaxis=dict(title="% del total"),
    xaxis=dict(title="Año", dtick=1),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    height=380,
)
st.plotly_chart(fig2, use_container_width=True)

with st.expander("Definiciones"):
    st.markdown(
        """
        Basado en `rsrv_status_extended` de `fact_reservations`, asignando la
        reserva al año de `rsrv_handover_date`.
        - **Served**: reservas con estado `Invoice` (se entrego el carro).
        - **Cancel cliente**: `Cancellation by Customer`.
        - **No-show cliente**: `No show` (cliente no se presento).
        - **Cancel Sixt**: `Cancellation by Sixt` (Sixt no entrego, p.ej. por
          falta de flota o cortesia).
        - **% served** = served / (served + cancel_cliente + noshow_cliente +
          cancel_sixt). Las reservas `Open`/`Offer` (no terminadas) quedan
          excluidas del denominador.
        """
    )
