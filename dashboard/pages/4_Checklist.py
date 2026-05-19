"""Checklist de apertura/cierre."""
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

st.set_page_config(page_title="Checklist - Trust", layout="wide")
inject_styles()
render_header("Checklist Apertura / Cierre")

with st.sidebar:
    st.markdown("## Filtros")
    brnc_code, brnc_name = branch_filter()
    fi, ff = date_range_filter()
    tipo = st.radio("Tipo", ["Ambos", "APERTURA", "CIERRE"], key="t4")

render_active_filters(brnc_name, fi, ff, extra=f"<strong>Tipo:</strong> {tipo}")

where_brnc = "" if brnc_code is None else f" AND c.brnc_code = {brnc_code} "
where_tipo = "" if tipo == "Ambos" else f" AND c.chkl_type = '{tipo}' "

base = f"WHERE c.chkl_date BETWEEN ? AND ? {where_brnc} {where_tipo}"

# KPIs
kpis_sql = f"""
SELECT COUNT(*) AS total,
       AVG(c.chkl_score) AS score_avg,
       SUM(CASE WHEN c.chkl_score < 5 THEN 1 ELSE 0 END) AS bajos,
       SUM(CASE WHEN c.chkl_score = 7 THEN 1 ELSE 0 END) AS perfectos
FROM op_checklist_apertura_cierre c
{base}
"""
k = load_query(kpis_sql, (fi.isoformat(), ff.isoformat())).iloc[0]

c1, c2, c3, c4 = st.columns(4)
kpi(c1, "Checklists realizados", fmt_int(k["total"]))
kpi(c2, "Score promedio (0-7)", f"{k['score_avg'] or 0:.2f}")
kpi(c3, "Score < 5 (incompletos)", fmt_int(k["bajos"]))
kpi(c4, "Score perfecto", fmt_int(k["perfectos"]))

# Heatmap por sede × ítem
section("Tasa de cumplimiento por ítem")
items_sql = f"""
SELECT
    AVG(c.chkl_caja_ok)*100 AS Caja,
    AVG(c.chkl_oficina_limpia)*100 AS Oficina_limpia,
    AVG(c.chkl_inventario_vehiculos_ok)*100 AS Inventario,
    AVG(c.chkl_documentos_organizados)*100 AS Documentos,
    AVG(c.chkl_sistema_operativo_ok)*100 AS Sistema,
    AVG(c.chkl_seguridad_ok)*100 AS Seguridad,
    AVG(c.chkl_combustible_disponible)*100 AS Combustible
FROM op_checklist_apertura_cierre c
{base}
"""
df = load_query(items_sql, (fi.isoformat(), ff.isoformat())).T.reset_index()
df.columns = ["Item", "Cumplimiento_%"]
fig = px.bar(df, x="Item", y="Cumplimiento_%", color_discrete_sequence=[SIXT_ORANGE])
fig.update_layout(**PLOTLY_LAYOUT, yaxis=dict(range=[0, 105]))
st.plotly_chart(fig, use_container_width=True)

# Por sede
if brnc_code is None:
    section("Score promedio por sede")
    sede_sql = f"""
    SELECT b.brnc_name AS sede, AVG(c.chkl_score) AS score_avg, COUNT(*) AS total
    FROM op_checklist_apertura_cierre c
    JOIN dim_branches b ON b.brnc_code = c.brnc_code
    {base}
    GROUP BY b.brnc_name ORDER BY score_avg DESC
    """
    df = load_query(sede_sql, (fi.isoformat(), ff.isoformat()))
    fig = px.bar(df, x="sede", y="score_avg", color_discrete_sequence=[SIXT_BLACK])
    fig.update_layout(**PLOTLY_LAYOUT, yaxis=dict(range=[0, 7.5]))
    st.plotly_chart(fig, use_container_width=True)

# Detalle
section("Detalle de checklists")
detalle_sql = f"""
SELECT c.chkl_date AS Fecha, b.brnc_name AS Sede, c.chkl_type AS Tipo,
       c.chkl_datm AS Hora, c.chkl_score AS Score, c.chkl_status AS Estado,
       c.chkl_caja_ok AS Caja, c.chkl_caja_monto AS Monto_Caja,
       c.chkl_oficina_limpia AS Oficina, c.chkl_inventario_vehiculos_ok AS Inv,
       c.chkl_documentos_organizados AS Docs, c.chkl_sistema_operativo_ok AS Sys,
       c.chkl_seguridad_ok AS Seg, c.chkl_combustible_disponible AS Comb,
       e.empl_name AS Realizado_por, c.chkl_observations AS Obs
FROM op_checklist_apertura_cierre c
JOIN dim_branches b ON b.brnc_code = c.brnc_code
LEFT JOIN dim_employees e ON e.empl_id = c.chkl_submitted_by
{base}
ORDER BY c.chkl_date DESC, b.brnc_name LIMIT 500
"""
df = load_query(detalle_sql, (fi.isoformat(), ff.isoformat()))
st.dataframe(df, use_container_width=True, hide_index=True, height=420)
