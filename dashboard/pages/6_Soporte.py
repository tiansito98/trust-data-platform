"""Solicitudes de soporte / escalamiento."""
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

st.set_page_config(page_title="Soporte - Trust", layout="wide")
inject_styles()
render_header("Solicitudes de Soporte / Escalamiento")

with st.sidebar:
    st.markdown("## Filtros")
    brnc_code, brnc_name = branch_filter()
    fi, ff = date_range_filter()

render_active_filters(brnc_name, fi, ff)

where_brnc = "" if brnc_code is None else f" AND s.brnc_code = {brnc_code} "
base = f"WHERE s.sopt_request_date BETWEEN ? AND ? {where_brnc}"

# KPIs
kpis_sql = f"""
SELECT COUNT(*) AS total,
       SUM(CASE WHEN s.sopt_status NOT IN ('RESUELTO','CERRADO') THEN 1 ELSE 0 END) AS abiertos,
       SUM(s.sopt_sla_breach_flg) AS breach,
       SUM(CASE WHEN s.sopt_priority='URGENTE' THEN 1 ELSE 0 END) AS urgentes
FROM op_solicitudes_soporte s
{base}
"""
k = load_query(kpis_sql, (fi.isoformat(), ff.isoformat())).iloc[0]
breach_pct = (k["breach"] / k["total"] * 100) if k["total"] else 0

c1, c2, c3, c4 = st.columns(4)
kpi(c1, "Total tickets", fmt_int(k["total"]))
kpi(c2, "En curso", fmt_int(k["abiertos"]))
kpi(c3, "SLA incumplido", fmt_int(k["breach"]), f"{breach_pct:.1f} % del total")
kpi(c4, "Urgentes", fmt_int(k["urgentes"]))

# Distribución
section("Distribución de tickets")
c1, c2 = st.columns(2)
with c1:
    sql = f"""
    SELECT s.sopt_category AS categoria, COUNT(*) AS n
    FROM op_solicitudes_soporte s
    {base}
    GROUP BY s.sopt_category ORDER BY n DESC
    """
    df = load_query(sql, (fi.isoformat(), ff.isoformat()))
    fig = px.bar(df, x="categoria", y="n", color_discrete_sequence=[SIXT_ORANGE], title="Por categoría")
    fig.update_layout(**PLOTLY_LAYOUT)
    st.plotly_chart(fig, use_container_width=True)

with c2:
    sql = f"""
    SELECT s.sopt_priority AS prioridad,
           SUM(CASE WHEN s.sopt_sla_breach_flg=1 THEN 1 ELSE 0 END) AS breach,
           SUM(CASE WHEN s.sopt_sla_breach_flg=0 THEN 1 ELSE 0 END) AS ok
    FROM op_solicitudes_soporte s
    {base}
    GROUP BY s.sopt_priority
    """
    df = load_query(sql, (fi.isoformat(), ff.isoformat()))
    fig = px.bar(df, x="prioridad", y=["ok", "breach"], title="SLA por prioridad",
                 color_discrete_map={"ok": SIXT_ORANGE, "breach": "#d32f2f"}, barmode="stack")
    fig.update_layout(**PLOTLY_LAYOUT)
    st.plotly_chart(fig, use_container_width=True)

# Tendencia
section("Tendencia mensual")
sql = f"""
SELECT strftime('%Y-%m', s.sopt_request_date) AS mes, COUNT(*) AS tickets,
       SUM(s.sopt_sla_breach_flg) AS breach
FROM op_solicitudes_soporte s
{base}
GROUP BY mes ORDER BY mes
"""
df = load_query(sql, (fi.isoformat(), ff.isoformat()))
fig = px.bar(df, x="mes", y=["tickets", "breach"], title="Tickets vs SLA incumplido por mes",
             color_discrete_map={"tickets": SIXT_ORANGE, "breach": SIXT_BLACK}, barmode="group")
fig.update_layout(**PLOTLY_LAYOUT)
st.plotly_chart(fig, use_container_width=True)

# Detalle
section("Detalle de tickets")
detalle_sql = f"""
SELECT s.sopt_request_date AS Fecha, b.brnc_name AS Sede,
       s.sopt_category AS Categoria, s.sopt_priority AS Prioridad, s.sopt_status AS Estado,
       s.sopt_subject AS Asunto, s.sopt_sla_hours AS SLA_h, s.sopt_sla_breach_flg AS Breach,
       e.empl_name AS Asignado_a, s.sopt_resolution_notes AS Notas
FROM op_solicitudes_soporte s
JOIN dim_branches b ON b.brnc_code = s.brnc_code
LEFT JOIN dim_employees e ON e.empl_id = s.sopt_assigned_to
{base}
ORDER BY s.sopt_request_date DESC LIMIT 500
"""
df = load_query(detalle_sql, (fi.isoformat(), ff.isoformat()))
st.dataframe(df, use_container_width=True, hide_index=True, height=420)
