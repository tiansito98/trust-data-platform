"""Validación de contratos / soportes faltantes."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import plotly.express as px
from components.common import (
    inject_styles, render_header, render_active_filters, kpi, section,
    branch_filter,
    load_query, fmt_int, PLOTLY_LAYOUT, SIXT_ORANGE, SIXT_BLACK
)

st.set_page_config(page_title="Soportes Faltantes - Trust", layout="wide")
inject_styles()
render_header("Contratos con Soportes Faltantes")

with st.sidebar:
    st.markdown("## Filtros")
    brnc_code, brnc_name = branch_filter()
    estado = st.multiselect("Estado", ["PENDIENTE", "EN_PROCESO", "SUBSANADO", "ESCALADO"],
                            default=["PENDIENTE", "EN_PROCESO", "ESCALADO"], key="e7")

render_active_filters(brnc_name, extra=f"<strong>Estados:</strong> {', '.join(estado) if estado else 'ninguno'}")

where_brnc = "" if brnc_code is None else f" AND c.brnc_code = {brnc_code} "
est_in = "','".join(estado) if estado else "NONE"
base = f"WHERE c.cosf_status IN ('{est_in}') {where_brnc}"

# KPIs
kpis_sql = f"""
SELECT COUNT(*) AS total,
       SUM(CASE WHEN c.cosf_severity IN ('ALTA','CRITICA') THEN 1 ELSE 0 END) AS criticos,
       SUM(CASE WHEN c.cosf_age_days > 7 THEN 1 ELSE 0 END) AS vencidos,
       SUM(CASE WHEN c.cosf_status='ESCALADO' THEN 1 ELSE 0 END) AS escalados
FROM op_contratos_soportes_faltantes c
{base}
"""
k = load_query(kpis_sql).iloc[0]
c1, c2, c3, c4 = st.columns(4)
kpi(c1, "Contratos pendientes", fmt_int(k["total"]))
kpi(c2, "Severidad ALTA/CRÍTICA", fmt_int(k["criticos"]))
kpi(c3, "Más de 7 días sin subsanar", fmt_int(k["vencidos"]))
kpi(c4, "Escalados", fmt_int(k["escalados"]))

# Distribución
section("Soportes faltantes — distribución")
c1, c2 = st.columns(2)
with c1:
    sql = f"""
    SELECT c.cosf_missing_type AS soporte, COUNT(*) AS n
    FROM op_contratos_soportes_faltantes c
    {base}
    GROUP BY c.cosf_missing_type ORDER BY n DESC
    """
    df = load_query(sql)
    fig = px.bar(df, x="soporte", y="n", color_discrete_sequence=[SIXT_ORANGE],
                 title="Por tipo de soporte faltante")
    fig.update_layout(**PLOTLY_LAYOUT)
    st.plotly_chart(fig, use_container_width=True)
with c2:
    sql = f"""
    SELECT c.cosf_severity AS sev, COUNT(*) AS n
    FROM op_contratos_soportes_faltantes c
    {base}
    GROUP BY c.cosf_severity
    """
    df = load_query(sql)
    fig = px.pie(df, names="sev", values="n", title="Por severidad",
                 color_discrete_sequence=[SIXT_ORANGE, "#f59e0b", "#666", "#d32f2f"])
    fig.update_layout(**PLOTLY_LAYOUT)
    st.plotly_chart(fig, use_container_width=True)

# Edad de pendientes
section("Antigüedad de contratos pendientes")
age_sql = f"""
SELECT
  CASE
    WHEN c.cosf_age_days <= 1 THEN '0-1 días'
    WHEN c.cosf_age_days <= 3 THEN '2-3 días'
    WHEN c.cosf_age_days <= 7 THEN '4-7 días'
    WHEN c.cosf_age_days <= 14 THEN '8-14 días'
    WHEN c.cosf_age_days <= 30 THEN '15-30 días'
    ELSE '30+ días'
  END AS rango,
  COUNT(*) AS n
FROM op_contratos_soportes_faltantes c
{base}
GROUP BY rango
ORDER BY MIN(c.cosf_age_days)
"""
df = load_query(age_sql)
fig = px.bar(df, x="rango", y="n", color_discrete_sequence=[SIXT_BLACK])
fig.update_layout(**PLOTLY_LAYOUT)
st.plotly_chart(fig, use_container_width=True)

# Detalle
section("Detalle de contratos pendientes")
detalle_sql = f"""
SELECT c.cosf_date AS Fecha, b.brnc_name AS Sede, c.rntl_mvnr AS Rental, c.rsrv_resn AS Reserva,
       cu.cstm_full_name AS Cliente, c.cosf_missing_type AS Soporte,
       c.cosf_missing_count AS N_Faltantes, c.cosf_severity AS Sev,
       c.cosf_age_days AS Dias, c.cosf_status AS Estado,
       e.empl_name AS Responsable, c.cosf_observations AS Obs
FROM op_contratos_soportes_faltantes c
JOIN dim_branches b ON b.brnc_code = c.brnc_code
LEFT JOIN dim_customers cu ON cu.cstm_kdnr = c.cstm_kdnr
LEFT JOIN dim_employees e ON e.empl_id = c.cosf_responsible
{base}
ORDER BY c.cosf_age_days DESC LIMIT 500
"""
df = load_query(detalle_sql)
st.dataframe(df, use_container_width=True, hide_index=True, height=420)
