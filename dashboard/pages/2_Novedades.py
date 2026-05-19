"""Novedades de vehículos."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import plotly.express as px
from components.common import (
    inject_styles, render_header, render_active_filters, kpi, section,
    branch_filter, date_range_filter,
    load_query, fmt_int, PLOTLY_LAYOUT, SIXT_ORANGE, SIXT_BLACK
)

st.set_page_config(page_title="Novedades - Trust", layout="wide")
inject_styles()
render_header("Novedades de Vehículos")

with st.sidebar:
    st.markdown("## Filtros")
    brnc_code, brnc_name = branch_filter()
    fi, ff = date_range_filter()
    sev = st.multiselect("Severidad", ["BAJA", "MEDIA", "ALTA", "CRITICA"], default=["MEDIA", "ALTA", "CRITICA"], key="s2")
    estado = st.multiselect("Estado", ["ABIERTA", "EN_GESTION", "RESUELTA", "ESCALADA"],
                            default=["ABIERTA", "EN_GESTION", "ESCALADA"], key="e2")

render_active_filters(brnc_name, fi, ff, extra=f"<strong>Sev:</strong> {', '.join(sev) if sev else '—'} &nbsp;|&nbsp; <strong>Estado:</strong> {', '.join(estado) if estado else '—'}")

where_brnc = "" if brnc_code is None else f" AND n.brnc_code = {brnc_code} "
sev_in = "','".join(sev) if sev else "NONE"
est_in = "','".join(estado) if estado else "NONE"

base_where = f"WHERE n.nove_date BETWEEN ? AND ? {where_brnc} AND n.nove_severity IN ('{sev_in}') AND n.nove_status IN ('{est_in}')"

# KPIs
kpis_sql = f"""
SELECT COUNT(*) AS total,
       SUM(CASE WHEN n.nove_status='ABIERTA' THEN 1 ELSE 0 END) AS abiertas,
       SUM(CASE WHEN n.nove_severity IN ('ALTA','CRITICA') THEN 1 ELSE 0 END) AS criticas,
       SUM(CASE WHEN n.nove_status='ESCALADA' THEN 1 ELSE 0 END) AS escaladas
FROM op_novedades_vehiculo n
{base_where}
"""
k = load_query(kpis_sql, (fi.isoformat(), ff.isoformat())).iloc[0]
c1, c2, c3, c4 = st.columns(4)
kpi(c1, "Total novedades", fmt_int(k["total"]))
kpi(c2, "Abiertas", fmt_int(k["abiertas"]))
kpi(c3, "Severas (ALTA/CRÍTICA)", fmt_int(k["criticas"]))
kpi(c4, "Escaladas", fmt_int(k["escaladas"]))

# Distribución por tipo
section("Distribución por tipo y severidad")
c1, c2 = st.columns(2)
with c1:
    tipo_sql = f"""
    SELECT n.nove_type AS tipo, COUNT(*) AS n
    FROM op_novedades_vehiculo n
    {base_where}
    GROUP BY n.nove_type ORDER BY n DESC
    """
    df = load_query(tipo_sql, (fi.isoformat(), ff.isoformat()))
    fig = px.bar(df, x="tipo", y="n", color_discrete_sequence=[SIXT_ORANGE], title="Por tipo de novedad")
    fig.update_layout(**PLOTLY_LAYOUT)
    st.plotly_chart(fig, use_container_width=True)

with c2:
    sev_sql = f"""
    SELECT n.nove_severity AS severidad, COUNT(*) AS n
    FROM op_novedades_vehiculo n
    {base_where}
    GROUP BY n.nove_severity
    """
    df = load_query(sev_sql, (fi.isoformat(), ff.isoformat()))
    fig = px.pie(df, names="severidad", values="n", title="Por severidad",
                 color_discrete_sequence=[SIXT_ORANGE, "#f59e0b", "#666", "#d32f2f"])
    fig.update_layout(**PLOTLY_LAYOUT)
    st.plotly_chart(fig, use_container_width=True)

# Top sedes
if brnc_code is None:
    section("Novedades por sede")
    sede_sql = f"""
    SELECT b.brnc_name AS sede, COUNT(*) AS n
    FROM op_novedades_vehiculo n
    JOIN dim_branches b ON b.brnc_code = n.brnc_code
    WHERE n.nove_date BETWEEN ? AND ? AND n.nove_severity IN ('{sev_in}') AND n.nove_status IN ('{est_in}')
    GROUP BY b.brnc_name ORDER BY n DESC
    """
    df = load_query(sede_sql, (fi.isoformat(), ff.isoformat()))
    fig = px.bar(df, y="sede", x="n", orientation="h", color_discrete_sequence=[SIXT_BLACK])
    fig.update_layout(**PLOTLY_LAYOUT)
    st.plotly_chart(fig, use_container_width=True)

# Detalle
section("Detalle de novedades")
detalle_sql = f"""
SELECT n.nove_date AS Fecha, b.brnc_name AS Sede, n.vhcl_plate AS Placa,
       n.nove_type AS Tipo, n.nove_severity AS Severidad, n.nove_status AS Estado,
       n.nove_description AS Descripcion, e.empl_name AS Reportado_por
FROM op_novedades_vehiculo n
JOIN dim_branches b ON b.brnc_code = n.brnc_code
LEFT JOIN dim_employees e ON e.empl_id = n.nove_reported_by
{base_where}
ORDER BY n.nove_date DESC LIMIT 500
"""
df = load_query(detalle_sql, (fi.isoformat(), ff.isoformat()))
st.dataframe(df, use_container_width=True, hide_index=True, height=400)
