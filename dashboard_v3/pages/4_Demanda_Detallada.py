"""Demanda detallada por sede x categoria ACRISS.

Muestra todos los indicadores de demanda (served, cancel cliente, no-show,
cancel Sixt) con la posibilidad de cortar por sede, ACRISS o ambos.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from components.common import (
    inject_styles, render_header, section, kpi,
    load_query, year_filter,
    SIXT_ORANGE, SIXT_BLACK, PLOTLY_LAYOUT,
    fmt_int, fmt_pct,
)

st.set_page_config(page_title="Demanda Detallada - Trust v3", layout="wide")
inject_styles()
render_header("Demanda - Detalle por sede y ACRISS")

lo_year, hi_year = year_filter("Rango de años")

base = load_query(f"""
    SELECT *
    FROM vw_demanda_sede_acriss_anual
    WHERE anio BETWEEN {lo_year} AND {hi_year}
    ORDER BY anio, sede, acriss
""")

if base.empty:
    st.warning("Sin datos en el rango.")
    st.stop()

# ---------- Filtros ----------

sedes = ["(Todas)"] + sorted(base["sede"].dropna().unique().tolist())
acriss_opts = ["(Todas)"] + sorted(base["acriss"].dropna().unique().tolist())
c1, c2, c3 = st.columns(3)
sede_sel = c1.selectbox("Sede", sedes)
acriss_sel = c2.selectbox("ACRISS", acriss_opts)
group_mode = c3.selectbox(
    "Agrupar por",
    ["Sede + ACRISS", "Solo sede", "Solo ACRISS", "Solo año"],
)

fdf = base.copy()
if sede_sel != "(Todas)":
    fdf = fdf[fdf["sede"] == sede_sel]
if acriss_sel != "(Todas)":
    fdf = fdf[fdf["acriss"] == acriss_sel]

if fdf.empty:
    st.info("Sin datos para esa combinacion de filtros.")
    st.stop()

# ---------- Agrupar segun seleccion ----------

GROUP_KEYS = {
    "Sede + ACRISS": ["anio", "sede", "acriss"],
    "Solo sede":     ["anio", "sede"],
    "Solo ACRISS":   ["anio", "acriss"],
    "Solo año":     ["anio"],
}
keys = GROUP_KEYS[group_mode]

agg = fdf.groupby(keys, as_index=False).agg(
    served=("served", "sum"),
    cancel_cliente=("cancel_cliente", "sum"),
    noshow_cliente=("noshow_cliente", "sum"),
    cancel_sixt=("cancel_sixt", "sum"),
    total_reservas=("total_reservas", "sum"),
)
agg["served_pct"]          = (agg["served"] / agg["total_reservas"] * 100).round(2)
agg["cancel_rate_pct"]     = ((agg["total_reservas"] - agg["served"]) / agg["total_reservas"] * 100).round(2)
agg["cancel_cliente_pct"]  = (agg["cancel_cliente"] / agg["total_reservas"] * 100).round(2)
agg["noshow_cliente_pct"]  = (agg["noshow_cliente"] / agg["total_reservas"] * 100).round(2)
agg["cancel_sixt_pct"]     = (agg["cancel_sixt"] / agg["total_reservas"] * 100).round(2)

# ---------- KPI cards (totales del filtro) ----------

total_res = int(agg["total_reservas"].sum())
total_served = int(agg["served"].sum())
total_cancel_cliente = int(agg["cancel_cliente"].sum())
total_noshow = int(agg["noshow_cliente"].sum())
total_cancel_sixt = int(agg["cancel_sixt"].sum())

c1, c2, c3, c4, c5 = st.columns(5)
kpi(c1, "Total reservas",   fmt_int(total_res))
kpi(c2, "% served",          fmt_pct(total_served / total_res * 100) if total_res else "-")
kpi(c3, "% cancel cliente",  fmt_pct(total_cancel_cliente / total_res * 100) if total_res else "-")
kpi(c4, "% no-show cliente", fmt_pct(total_noshow / total_res * 100) if total_res else "-")
kpi(c5, "% cancel Sixt",     fmt_pct(total_cancel_sixt / total_res * 100) if total_res else "-")

# ---------- Tabla ----------

section(f"Detalle agrupado por: {group_mode}")

display = agg.copy()
for c in ("served", "cancel_cliente", "noshow_cliente", "cancel_sixt", "total_reservas"):
    display[c] = display[c].map(fmt_int)
for c in ("served_pct", "cancel_rate_pct", "cancel_cliente_pct", "noshow_cliente_pct", "cancel_sixt_pct"):
    display[c] = display[c].map(fmt_pct)

st.dataframe(display, hide_index=True, use_container_width=True, height=350)

# ---------- Charts ----------

# Si el grupo es solo anio: barras stacked clasicas
# Si tiene sede o acriss: heatmap de % served en (sede x acriss) o (anio x grupo)

if group_mode == "Solo año":
    section("Composición de la demanda por año")
    fig = go.Figure()
    fig.add_bar(x=agg["anio"], y=agg["served"],           name="Served",          marker_color=SIXT_ORANGE)
    fig.add_bar(x=agg["anio"], y=agg["cancel_cliente"],   name="Cancel cliente",  marker_color="#666666")
    fig.add_bar(x=agg["anio"], y=agg["noshow_cliente"],   name="No-show cliente", marker_color="#999999")
    fig.add_bar(x=agg["anio"], y=agg["cancel_sixt"],      name="Cancel Sixt",     marker_color=SIXT_BLACK)
    fig.update_layout(
        **PLOTLY_LAYOUT,
        barmode="stack",
        yaxis=dict(title="Reservas"),
        xaxis=dict(title="Año", dtick=1),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        height=420,
    )
    st.plotly_chart(fig, use_container_width=True)

elif "sede" in keys and "acriss" in keys:
    section("% served por sede x ACRISS (heatmap)")
    # Si solo hay 1 anio en el filtro, mostrar matriz sede x acriss
    # Si hay varios, promediar
    pivot = fdf.groupby(["sede", "acriss"], as_index=False).agg(
        served=("served", "sum"),
        total=("total_reservas", "sum"),
    )
    pivot["served_pct"] = (pivot["served"] / pivot["total"] * 100).round(1)
    heat = pivot.pivot(index="sede", columns="acriss", values="served_pct")
    fig = px.imshow(
        heat,
        color_continuous_scale=[[0, "#d32f2f"], [0.5, "#f59e0b"], [1, "#2e7d32"]],
        zmin=0, zmax=100,
        labels=dict(color="% served"),
        text_auto=".1f",
        aspect="auto",
    )
    fig.update_layout(**PLOTLY_LAYOUT, height=440,
                      title=f"% served por sede x ACRISS ({lo_year}-{hi_year})")
    st.plotly_chart(fig, use_container_width=True)

    section("Cancel rate por sede x ACRISS")
    pivot2 = pivot.copy()
    pivot2["cancel_rate"] = (100 - pivot2["served_pct"]).round(1)
    heat2 = pivot2.pivot(index="sede", columns="acriss", values="cancel_rate")
    fig2 = px.imshow(
        heat2,
        color_continuous_scale=[[0, "#2e7d32"], [0.5, "#f59e0b"], [1, "#d32f2f"]],
        zmin=0, zmax=100,
        labels=dict(color="% cancel rate"),
        text_auto=".1f",
        aspect="auto",
    )
    fig2.update_layout(**PLOTLY_LAYOUT, height=440)
    st.plotly_chart(fig2, use_container_width=True)

else:
    # Series temporales por grupo
    section("% served - evolución por grupo")
    group_col = "sede" if "sede" in keys else "acriss"
    pivot = agg.pivot(index="anio", columns=group_col, values="served_pct")
    fig = go.Figure()
    palette = px.colors.qualitative.Set2
    for i, col in enumerate(pivot.columns):
        fig.add_scatter(
            x=pivot.index, y=pivot[col],
            mode="lines+markers", name=str(col),
            line=dict(color=palette[i % len(palette)], width=2),
        )
    fig.update_layout(
        **PLOTLY_LAYOUT,
        yaxis=dict(title="% served", range=[0, 100]),
        xaxis=dict(title="Año", dtick=1),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        height=420,
    )
    st.plotly_chart(fig, use_container_width=True)

    section("Volumen total de reservas")
    pivot_vol = agg.pivot(index="anio", columns=group_col, values="total_reservas")
    fig2 = px.bar(
        pivot_vol.reset_index().melt(id_vars="anio", value_name="reservas"),
        x="anio", y="reservas", color=group_col, barmode="stack",
    )
    fig2.update_layout(**PLOTLY_LAYOUT, height=420,
                       xaxis=dict(title="Año", dtick=1),
                       legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
    st.plotly_chart(fig2, use_container_width=True)

# ---------- Worst offenders ----------

if group_mode != "Solo año":
    section("Combinaciones con peor served % (volumen significativo)")
    # Solo mostrar las que tienen al menos 50 reservas para no ruido
    worst = agg[agg["total_reservas"] >= 50].sort_values("served_pct").head(15)
    if not worst.empty:
        display_worst = worst.copy()
        for c in ("served", "total_reservas"):
            display_worst[c] = display_worst[c].map(fmt_int)
        display_worst["served_pct"] = display_worst["served_pct"].map(fmt_pct)
        display_worst["cancel_rate_pct"] = display_worst["cancel_rate_pct"].map(fmt_pct)
        st.dataframe(
            display_worst[[*keys, "served", "total_reservas", "served_pct", "cancel_rate_pct"]],
            hide_index=True, use_container_width=True,
        )

with st.expander("Notas y limitaciones"):
    st.markdown(
        """
        - **ACRISS = RESERVADO** (`vhgr_crs` de la reserva). Las reservas
          canceladas / no-show nunca tuvieron rental, asi que no hay ACRISS
          entregado para ellas. Por consistencia, usamos el reservado tambien
          para las que si fueron `Invoice`.
        - **Sede = sede de handover de la reserva** (`brnc_code_handover`).
        - Las reservas `Open` y `Offer` (no terminadas) quedan **excluidas**
          del denominador.
        - El filtro "Combinaciones con peor served %" solo muestra
          combinaciones con >= 50 reservas para evitar outliers de bajo
          volumen.
        """
    )
