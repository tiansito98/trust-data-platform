"""
TRUST - Operacion Diaria
Resumen ejecutivo. Consulta data/silver.db (vistas derivadas + dimensiones).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from components.common import (
    inject_styles, render_header, render_active_filters, kpi, section, branch_filter,
    date_range_filter, load_query, fmt_cop, fmt_int, fmt_cop_short,
    PLOTLY_LAYOUT, SIXT_ORANGE, SIXT_BLACK,
)

st.set_page_config(
    page_title="Trust - Operacion Diaria",
    layout="wide",
    initial_sidebar_state="expanded",
)
inject_styles()
render_header("Resumen Ejecutivo")

# Sidebar
with st.sidebar:
    st.markdown("## Filtros globales")
    brnc_code, brnc_name = branch_filter()
    fecha_inicio, fecha_fin = date_range_filter(default_days=30)
    st.markdown("---")
    st.markdown("### Reportes operativos")
    st.markdown("Use el menu lateral para navegar entre los 7 reportes.")
    st.markdown("---")
    st.caption(
        "**Fuente:** Redshift Data Exchange de Sixt Colombia (mandant 409). "
        "El cierre diario se deriva de Tramo 1 (rentals + charges + flota); "
        "el resto de operativos los captura Trust en sus tablas op_*."
    )

# Filtros para queries
where_brnc = "" if brnc_code is None else f" AND brnc_code = {brnc_code} "

# ========== KPIs principales (derivados de Tramo 1) ==========
kpis_sql = f"""
SELECT
    COALESCE(SUM(cier_revenue_total), 0) AS revenue,
    COALESCE(SUM(cier_rentals_count), 0) AS rentals,
    COALESCE(SUM(cier_returns_count), 0) AS returns,
    COALESCE(AVG(cier_vehicles_rented * 1.0 / NULLIF(cier_vehicles_in_branch, 0)), 0) AS occupancy
FROM vw_cierre_diario_sede
WHERE 1=1 {where_brnc}
  AND cier_date BETWEEN ? AND ?
"""
kpis_df = load_query(kpis_sql, (fecha_inicio.isoformat(), fecha_fin.isoformat()))
revenue = kpis_df["revenue"].iloc[0]
rentals = kpis_df["rentals"].iloc[0]
returns = kpis_df["returns"].iloc[0]
occupancy = kpis_df["occupancy"].iloc[0] * 100

# Pendientes / alertas (capturados por Trust en op_*; vacios hoy)
incidentes_abiertos = load_query(
    f"SELECT COUNT(*) AS n FROM op_incidentes WHERE inci_status NOT IN ('CERRADO') {where_brnc} AND inci_date BETWEEN ? AND ?",
    (fecha_inicio.isoformat(), fecha_fin.isoformat()),
)["n"].iloc[0]

soportes_pendientes = load_query(
    f"SELECT COUNT(*) AS n FROM op_contratos_soportes_faltantes WHERE cosf_status NOT IN ('SUBSANADO') {where_brnc}",
)["n"].iloc[0]

novedades_abiertas = load_query(
    f"SELECT COUNT(*) AS n FROM op_novedades_vehiculo WHERE nove_status NOT IN ('RESUELTA') {where_brnc} AND nove_date BETWEEN ? AND ?",
    (fecha_inicio.isoformat(), fecha_fin.isoformat()),
)["n"].iloc[0]

soporte_breach = load_query(
    f"SELECT COUNT(*) AS n FROM op_solicitudes_soporte WHERE sopt_sla_breach_flg=1 {where_brnc} AND sopt_request_date BETWEEN ? AND ?",
    (fecha_inicio.isoformat(), fecha_fin.isoformat()),
)["n"].iloc[0]

render_active_filters(brnc_name, fecha_inicio, fecha_fin)

c1, c2, c3, c4 = st.columns(4)
kpi(c1, "Revenue del periodo", fmt_cop(revenue), fmt_cop_short(revenue))
kpi(c2, "Rentals (entregas)", fmt_int(rentals))
kpi(c3, "Devoluciones", fmt_int(returns))
kpi(c4, "Ocupacion promedio", f"{occupancy:.1f} %")

c5, c6, c7, c8 = st.columns(4)
kpi(c5, "Incidentes abiertos", fmt_int(incidentes_abiertos))
kpi(c6, "Soportes faltantes", fmt_int(soportes_pendientes))
kpi(c7, "Novedades abiertas", fmt_int(novedades_abiertas))
kpi(c8, "SLA incumplido", fmt_int(soporte_breach))

# ========== Charts ==========
# Si "Todas las sedes": hue por sede en tendencia (click leyenda para aislar).
# Si una sede: tendencia con una sola serie.
section("Tendencia operativa diaria")

if brnc_code is None:
    trend_sql = """
    SELECT c.cier_date AS fecha,
           b.brnc_name AS sede,
           SUM(c.cier_rentals_count) AS rentals,
           SUM(c.cier_returns_count) AS returns,
           SUM(c.cier_revenue_total) AS revenue
    FROM vw_cierre_diario_sede c
    JOIN dim_branches b ON b.brnc_code = c.brnc_code
    WHERE c.cier_date BETWEEN ? AND ?
    GROUP BY c.cier_date, b.brnc_name
    ORDER BY c.cier_date, b.brnc_name
    """
    trend_df = load_query(trend_sql, (fecha_inicio.isoformat(), fecha_fin.isoformat()))
    trend_df["fecha"] = pd.to_datetime(trend_df["fecha"])

    c1, c2 = st.columns(2)
    with c1:
        fig = px.line(
            trend_df, x="fecha", y="rentals", color="sede",
            title="Rentals por sede (clic en la leyenda para aislar)",
            markers=False,
        )
        fig.update_layout(**PLOTLY_LAYOUT, legend=dict(orientation="h", y=-0.2))
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        fig = px.bar(
            trend_df, x="fecha", y="revenue", color="sede", barmode="stack",
            title="Revenue diario apilado por sede (COP)",
        )
        fig.update_layout(**PLOTLY_LAYOUT, yaxis_tickformat=",.0f", legend=dict(orientation="h", y=-0.2))
        st.plotly_chart(fig, use_container_width=True)
else:
    trend_sql = f"""
    SELECT cier_date AS fecha,
           SUM(cier_rentals_count) AS rentals,
           SUM(cier_returns_count) AS returns,
           SUM(cier_revenue_total) AS revenue
    FROM vw_cierre_diario_sede
    WHERE 1=1 {where_brnc} AND cier_date BETWEEN ? AND ?
    GROUP BY cier_date
    ORDER BY cier_date
    """
    trend_df = load_query(trend_sql, (fecha_inicio.isoformat(), fecha_fin.isoformat()))
    trend_df["fecha"] = pd.to_datetime(trend_df["fecha"])

    c1, c2 = st.columns(2)
    with c1:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=trend_df["fecha"], y=trend_df["rentals"], name="Rentals",
                                 line=dict(color=SIXT_ORANGE, width=3)))
        fig.add_trace(go.Scatter(x=trend_df["fecha"], y=trend_df["returns"], name="Devoluciones",
                                 line=dict(color=SIXT_BLACK, width=2, dash="dot")))
        fig.update_layout(title="Rentals vs Devoluciones", **PLOTLY_LAYOUT)
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        fig = go.Figure()
        fig.add_trace(go.Bar(x=trend_df["fecha"], y=trend_df["revenue"], marker_color=SIXT_ORANGE))
        fig.update_layout(title="Revenue diario (COP)", **PLOTLY_LAYOUT, yaxis_tickformat=",.0f")
        st.plotly_chart(fig, use_container_width=True)

# ========== Ranking sedes ==========
if brnc_code is None:
    section("Ranking de sedes")
    ranking_sql = """
    SELECT b.brnc_name AS sede, b.brnc_city AS ciudad,
           COALESCE(SUM(c.cier_rentals_count), 0) AS rentals,
           COALESCE(SUM(c.cier_revenue_total), 0) AS revenue,
           COALESCE(AVG(c.cier_vehicles_rented * 1.0 / NULLIF(c.cier_vehicles_in_branch, 0)), 0) * 100 AS ocupacion_pct,
           COUNT(c.cier_date) AS dias_con_actividad
    FROM dim_branches b
    LEFT JOIN vw_cierre_diario_sede c
      ON c.brnc_code = b.brnc_code
     AND c.cier_date BETWEEN ? AND ?
    GROUP BY b.brnc_name, b.brnc_city
    ORDER BY revenue DESC
    """
    ranking_df = load_query(ranking_sql, (fecha_inicio.isoformat(), fecha_fin.isoformat()))
    ranking_df["revenue_fmt"] = ranking_df["revenue"].apply(fmt_cop)
    ranking_df["rentals_fmt"] = ranking_df["rentals"].apply(fmt_int)
    ranking_df["ocupacion_fmt"] = ranking_df["ocupacion_pct"].apply(lambda x: f"{x:.1f} %")
    ranking_df["dias_fmt"] = ranking_df["dias_con_actividad"].apply(fmt_int)

    st.dataframe(
        ranking_df[["sede", "ciudad", "rentals_fmt", "revenue_fmt", "ocupacion_fmt", "dias_fmt"]].rename(
            columns={
                "sede": "Sede", "ciudad": "Ciudad", "rentals_fmt": "Rentals",
                "revenue_fmt": "Revenue", "ocupacion_fmt": "Ocupacion",
                "dias_fmt": "Dias con actividad",
            }
        ),
        use_container_width=True, hide_index=True,
    )

    c1, c2 = st.columns(2)
    with c1:
        fig = px.bar(
            ranking_df, x="sede", y="revenue", color_discrete_sequence=[SIXT_ORANGE],
            title="Revenue por sede (COP)",
        )
        fig.update_layout(**PLOTLY_LAYOUT, yaxis_tickformat=",.0f")
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        fig = px.bar(
            ranking_df, x="sede", y="ocupacion_pct", color_discrete_sequence=[SIXT_BLACK],
            title="Ocupacion promedio (%)",
        )
        fig.update_layout(**PLOTLY_LAYOUT)
        st.plotly_chart(fig, use_container_width=True)

# ========== Distribucion por categoria ==========
section("Mix de flota por categoria")
mix_sql = f"""
SELECT vhgr_category_level2 AS categoria,
       vhgr_category_level1 AS tipo,
       COUNT(*) AS vehiculos
FROM vw_vehicle_current_state
WHERE 1=1 {where_brnc}
GROUP BY vhgr_category_level2, vhgr_category_level1
ORDER BY vehiculos DESC
"""
mix_df = load_query(mix_sql)

if not mix_df.empty:
    c1, c2 = st.columns(2)
    with c1:
        fig = px.sunburst(
            mix_df, path=["categoria", "tipo"], values="vehiculos",
            color_discrete_sequence=[SIXT_ORANGE, SIXT_BLACK, "#666", "#999", "#ccc", "#fdb"],
        )
        fig.update_layout(title="Composicion de flota", **PLOTLY_LAYOUT)
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        agg = mix_df.groupby("categoria", as_index=False)["vehiculos"].sum().sort_values("vehiculos")
        fig = px.bar(
            agg, y="categoria", x="vehiculos", orientation="h",
            color_discrete_sequence=[SIXT_ORANGE], title="Vehiculos por categoria",
        )
        fig.update_layout(**PLOTLY_LAYOUT)
        st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No hay vehiculos para los filtros seleccionados.")

st.markdown("---")
st.caption(
    "Trust Data Platform - Bronze + Silver sobre SQLite local. "
    "Refresh incremental desde Redshift cada 6 horas."
)
