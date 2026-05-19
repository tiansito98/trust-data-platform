"""Traslados de vehículos inter-sede."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from components.common import (
    inject_styles, render_header, render_active_filters, kpi, section,
    branch_filter, date_range_filter,
    load_query, fmt_int, fmt_cop, PLOTLY_LAYOUT, SIXT_ORANGE, SIXT_BLACK
)

st.set_page_config(page_title="Traslados - Trust", layout="wide")
inject_styles()
render_header("Traslados Inter-Sede")

with st.sidebar:
    st.markdown("## Filtros")
    brnc_code, brnc_name = branch_filter()
    fi, ff = date_range_filter()

render_active_filters(brnc_name, fi, ff)

if brnc_code is None:
    where_brnc = ""
else:
    where_brnc = f" AND (t.brnc_code_origin = {brnc_code} OR t.brnc_code_destination = {brnc_code}) "

base = f"WHERE t.tras_request_date BETWEEN ? AND ? {where_brnc}"

# KPIs
kpis_sql = f"""
SELECT COUNT(*) AS total,
       SUM(CASE WHEN t.tras_status='COMPLETADO' THEN 1 ELSE 0 END) AS completados,
       SUM(CASE WHEN t.tras_status IN ('SOLICITADO','APROBADO','EN_TRANSITO') THEN 1 ELSE 0 END) AS pendientes,
       SUM(t.tras_cost) AS costo_total,
       AVG(t.tras_distance_km) AS dist_avg
FROM op_traslado_vehiculos t
{base}
"""
k = load_query(kpis_sql, (fi.isoformat(), ff.isoformat())).iloc[0]

c1, c2, c3, c4 = st.columns(4)
kpi(c1, "Total traslados", fmt_int(k["total"]))
kpi(c2, "Completados", fmt_int(k["completados"]))
kpi(c3, "En curso", fmt_int(k["pendientes"]))
kpi(c4, "Costo acumulado", fmt_cop(k["costo_total"]))

# Distribución
section("Distribución por motivo y prioridad")
c1, c2 = st.columns(2)
with c1:
    sql = f"""
    SELECT t.tras_reason AS motivo, COUNT(*) AS n
    FROM op_traslado_vehiculos t
    {base}
    GROUP BY t.tras_reason ORDER BY n DESC
    """
    df = load_query(sql, (fi.isoformat(), ff.isoformat()))
    fig = px.bar(df, x="motivo", y="n", color_discrete_sequence=[SIXT_ORANGE], title="Por motivo")
    fig.update_layout(**PLOTLY_LAYOUT)
    st.plotly_chart(fig, use_container_width=True)
with c2:
    sql = f"""
    SELECT t.tras_priority AS prioridad, COUNT(*) AS n
    FROM op_traslado_vehiculos t
    {base}
    GROUP BY t.tras_priority
    """
    df = load_query(sql, (fi.isoformat(), ff.isoformat()))
    fig = px.pie(df, names="prioridad", values="n", title="Por prioridad",
                 color_discrete_sequence=[SIXT_ORANGE, "#f59e0b", "#666", "#d32f2f"])
    fig.update_layout(**PLOTLY_LAYOUT)
    st.plotly_chart(fig, use_container_width=True)

# Flujo origen → destino
section("Flujo entre sedes")
flow_sql = f"""
SELECT bo.brnc_name AS origen, bd.brnc_name AS destino, COUNT(*) AS n,
       SUM(t.tras_cost) AS costo, AVG(t.tras_duration_hours) AS horas
FROM op_traslado_vehiculos t
JOIN dim_branches bo ON bo.brnc_code = t.brnc_code_origin
JOIN dim_branches bd ON bd.brnc_code = t.brnc_code_destination
{base}
GROUP BY bo.brnc_name, bd.brnc_name
ORDER BY n DESC
"""
df = load_query(flow_sql, (fi.isoformat(), ff.isoformat()))
df["costo"] = df["costo"].apply(fmt_cop)
df["horas"] = df["horas"].apply(lambda x: f"{x:.1f}")
st.dataframe(df.rename(columns={"origen": "Origen", "destino": "Destino", "n": "Traslados",
                                 "costo": "Costo total", "horas": "Duración promedio (h)"}),
             use_container_width=True, hide_index=True)

# Detalle
section("Detalle de traslados")
detalle_sql = f"""
SELECT t.tras_request_date AS Solicitud, t.vhcl_plate AS Placa,
       bo.brnc_name AS Origen, bd.brnc_name AS Destino,
       t.tras_reason AS Motivo, t.tras_priority AS Prioridad, t.tras_status AS Estado,
       t.tras_distance_km AS Km, t.tras_duration_hours AS Horas, t.tras_cost AS Costo,
       t.tras_observations AS Obs
FROM op_traslado_vehiculos t
JOIN dim_branches bo ON bo.brnc_code = t.brnc_code_origin
JOIN dim_branches bd ON bd.brnc_code = t.brnc_code_destination
{base}
ORDER BY t.tras_request_date DESC LIMIT 500
"""
df = load_query(detalle_sql, (fi.isoformat(), ff.isoformat()))
df["Costo"] = df["Costo"].apply(fmt_cop)
st.dataframe(df, use_container_width=True, hide_index=True, height=420)
