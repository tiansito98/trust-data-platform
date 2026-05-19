"""Incidentes operativos."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import plotly.express as px
from components.common import (
    inject_styles, render_header, render_active_filters, kpi, section,
    branch_filter, date_range_filter,
    load_query, fmt_int, fmt_cop, PLOTLY_LAYOUT, SIXT_ORANGE, SIXT_BLACK
)

st.set_page_config(page_title="Incidentes - Trust", layout="wide")
inject_styles()
render_header("Incidentes Operativos")

with st.sidebar:
    st.markdown("## Filtros")
    brnc_code, brnc_name = branch_filter()
    fi, ff = date_range_filter()
    sev = st.multiselect("Severidad", ["BAJA", "MEDIA", "ALTA", "CRITICA"],
                         default=["BAJA", "MEDIA", "ALTA", "CRITICA"], key="s3")

render_active_filters(brnc_name, fi, ff, extra=f"<strong>Sev:</strong> {', '.join(sev) if sev else '—'}")

where_brnc = "" if brnc_code is None else f" AND i.brnc_code = {brnc_code} "
sev_in = "','".join(sev) if sev else "NONE"

base_where = f"WHERE i.inci_date BETWEEN ? AND ? {where_brnc} AND i.inci_severity IN ('{sev_in}')"

# KPIs
kpis_sql = f"""
SELECT COUNT(*) AS total,
       SUM(CASE WHEN i.inci_status NOT IN ('CERRADO') THEN 1 ELSE 0 END) AS abiertos,
       SUM(CASE WHEN i.inci_severity='CRITICA' THEN 1 ELSE 0 END) AS criticos,
       SUM(i.inci_estimated_cost) AS costo_total
FROM op_incidentes i
{base_where}
"""
k = load_query(kpis_sql, (fi.isoformat(), ff.isoformat())).iloc[0]
c1, c2, c3, c4 = st.columns(4)
kpi(c1, "Total incidentes", fmt_int(k["total"]))
kpi(c2, "En curso", fmt_int(k["abiertos"]))
kpi(c3, "Críticos", fmt_int(k["criticos"]))
kpi(c4, "Costo estimado total", fmt_cop(k["costo_total"]))

# Distribución
section("Distribución por tipo y estado")
c1, c2 = st.columns(2)
with c1:
    tipo_sql = f"""
    SELECT i.inci_type AS tipo, COUNT(*) AS n
    FROM op_incidentes i
    {base_where}
    GROUP BY i.inci_type ORDER BY n DESC
    """
    df = load_query(tipo_sql, (fi.isoformat(), ff.isoformat()))
    fig = px.bar(df, x="tipo", y="n", color_discrete_sequence=[SIXT_ORANGE], title="Por tipo")
    fig.update_layout(**PLOTLY_LAYOUT)
    st.plotly_chart(fig, use_container_width=True)
with c2:
    estado_sql = f"""
    SELECT i.inci_status AS estado, COUNT(*) AS n
    FROM op_incidentes i
    {base_where}
    GROUP BY i.inci_status
    """
    df = load_query(estado_sql, (fi.isoformat(), ff.isoformat()))
    fig = px.pie(df, names="estado", values="n", title="Por estado",
                 color_discrete_sequence=[SIXT_ORANGE, SIXT_BLACK, "#666", "#999"])
    fig.update_layout(**PLOTLY_LAYOUT)
    st.plotly_chart(fig, use_container_width=True)

# Tendencia
section("Tendencia mensual")
trend_sql = f"""
SELECT strftime('%Y-%m', i.inci_date) AS mes,
       COUNT(*) AS n,
       SUM(i.inci_estimated_cost) AS costo
FROM op_incidentes i
{base_where}
GROUP BY mes ORDER BY mes
"""
df = load_query(trend_sql, (fi.isoformat(), ff.isoformat()))
fig = px.bar(df, x="mes", y="n", color_discrete_sequence=[SIXT_ORANGE], title="Incidentes por mes")
fig.update_layout(**PLOTLY_LAYOUT)
st.plotly_chart(fig, use_container_width=True)

# Detalle
section("Detalle de incidentes")
detalle_sql = f"""
SELECT i.inci_date AS Fecha, b.brnc_name AS Sede, v.vhcl_plate AS Placa, i.rntl_mvnr AS Rental,
       i.inci_type AS Tipo, i.inci_severity AS Severidad, i.inci_status AS Estado,
       i.inci_estimated_cost AS Costo_Est, i.inci_third_party_flg AS Tercero,
       i.inci_police_flg AS Policia, i.inci_insurance_flg AS Aseguradora,
       i.inci_description AS Descripcion
FROM op_incidentes i
JOIN dim_branches b ON b.brnc_code = i.brnc_code
LEFT JOIN dim_vehicles v ON v.vhcl_int_num = i.vhcl_int_num
{base_where}
ORDER BY i.inci_date DESC LIMIT 500
"""
df = load_query(detalle_sql, (fi.isoformat(), ff.isoformat()))
df["Costo_Est"] = df["Costo_Est"].apply(fmt_cop)
st.dataframe(df, use_container_width=True, hide_index=True, height=420)
