"""Cierre Diario de Sede - dashboard operativo derivado de Tramo 1.

Todo el contenido se calcula desde fact_reservations + fact_rentals + dim_*.
No requiere captura humana en op_*. Las tablas op_* siguen disponibles para
captura futura, pero esta vista las reemplaza con valores derivados.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from components.common import (
    inject_styles, render_header, render_active_filters, kpi, section,
    branch_filter, date_range_filter,
    load_query, fmt_cop, fmt_int, fmt_cop_short, PLOTLY_LAYOUT, SIXT_ORANGE, SIXT_BLACK,
)

st.set_page_config(page_title="Cierre Diario - Trust", layout="wide")
inject_styles()
render_header("Cierre Diario de Sede")

with st.sidebar:
    st.markdown("## Filtros")
    brnc_code, brnc_name = branch_filter()
    fi, ff = date_range_filter()

render_active_filters(brnc_name, fi, ff)

# Filtros base por sede de handover
where_brnc_h = "" if brnc_code is None else f" AND r.brnc_code_handover = {brnc_code} "
where_brnc_v = "" if brnc_code is None else f" AND vc.brnc_code = {brnc_code} "
where_brnc_c = "" if brnc_code is None else f" AND c.brnc_code = {brnc_code} "

# =============================================================================
# 1. KPIs OPERATIVOS (cierre derivado de Tramo 1)
# =============================================================================
section("Resumen del periodo")

kpis_sql = f"""
SELECT
    COUNT(DISTINCT c.cier_date)            AS dias,
    COUNT(DISTINCT c.brnc_code)            AS sedes,
    COALESCE(SUM(c.cier_rentals_count), 0) AS rentals,
    COALESCE(SUM(c.cier_returns_count), 0) AS returns,
    COALESCE(SUM(c.cier_revenue_total), 0) AS revenue
FROM vw_cierre_diario_sede c
WHERE c.cier_date BETWEEN ? AND ? {where_brnc_c}
"""
k = load_query(kpis_sql, (fi.isoformat(), ff.isoformat())).iloc[0]

c1, c2, c3, c4 = st.columns(4)
kpi(c1, "Rentals (entregas)", fmt_int(k["rentals"]))
kpi(c2, "Devoluciones", fmt_int(k["returns"]))
kpi(c3, "Revenue total", fmt_cop(k["revenue"]), fmt_cop_short(k["revenue"]))
ticket = (k["revenue"] / k["rentals"]) if k["rentals"] else 0
kpi(c4, "Ticket promedio / rental", fmt_cop(ticket))

c5, c6, c7, c8 = st.columns(4)
kpi(c5, "Dias con actividad", fmt_int(k["dias"]))
kpi(c6, "Sedes activas", fmt_int(k["sedes"]))
ratio = (k["returns"] / k["rentals"]) if k["rentals"] else 0
kpi(c7, "Devoluciones / rentals", f"{ratio:.2f}")
# Avg rentals/dia
avg_rentals_day = (k["rentals"] / k["dias"]) if k["dias"] else 0
kpi(c8, "Rentals / dia (promedio)", f"{avg_rentals_day:.1f}")

# =============================================================================
# 2. DEMANDA Y CONVERSION (basado en fact_reservations)
# =============================================================================
section("Demanda y conversion")

dem_sql = f"""
SELECT
    COUNT(*) AS reservas_totales,
    SUM(CASE WHEN r.rsrv_status='Processed' AND r.rsrv_status_extended='Invoice' THEN 1 ELSE 0 END) AS procesadas,
    SUM(CASE WHEN r.rsrv_status='Cancelled' AND r.rsrv_status_extended='Cancellation by Customer' THEN 1 ELSE 0 END) AS canc_cliente,
    SUM(CASE WHEN r.rsrv_status='Cancelled' AND r.rsrv_status_extended='Cancellation by Sixt' THEN 1 ELSE 0 END) AS canc_sixt,
    SUM(CASE WHEN r.rsrv_noshow_flg = 1 THEN 1 ELSE 0 END) AS no_show,
    SUM(CASE WHEN r.rsrv_status='Open' THEN 1 ELSE 0 END) AS open_,
    SUM(CASE WHEN r.rsrv_status='Offer' THEN 1 ELSE 0 END) AS offer_
FROM fact_reservations r
WHERE r.rsrv_handover_date BETWEEN ? AND ? {where_brnc_h}
"""
d = load_query(dem_sql, (fi.isoformat(), ff.isoformat())).iloc[0]
total = d["reservas_totales"] or 1

c1, c2, c3, c4 = st.columns(4)
kpi(c1, "Demanda total (reservas)", fmt_int(d["reservas_totales"]))
kpi(c2, "Procesadas (a contrato)", fmt_int(d["procesadas"]),
    f"{(d['procesadas']/total*100):.1f} % del total")
kpi(c3, "Canceladas por cliente", fmt_int(d["canc_cliente"]),
    f"{(d['canc_cliente']/total*100):.1f} % del total")
kpi(c4, "No-show", fmt_int(d["no_show"]),
    f"{(d['no_show']/total*100):.1f} % del total")

c5, c6, c7, c8 = st.columns(4)
kpi(c5, "Canceladas por Sixt", fmt_int(d["canc_sixt"]),
    f"{(d['canc_sixt']/total*100):.1f} % del total")
kpi(c6, "Open (en curso)", fmt_int(d["open_"]))
kpi(c7, "Offer (cotizaciones)", fmt_int(d["offer_"]))
demanda_perdida = d["canc_cliente"] + d["canc_sixt"] + d["no_show"]
kpi(c8, "Demanda perdida", fmt_int(demanda_perdida),
    f"{(demanda_perdida/total*100):.1f} % del total")

# Stacked bar: estado por dia
dem_trend_sql = f"""
SELECT DATE(r.rsrv_handover_date) AS fecha,
    SUM(CASE WHEN r.rsrv_status='Processed' AND r.rsrv_status_extended='Invoice' THEN 1 ELSE 0 END) AS Procesadas,
    SUM(CASE WHEN r.rsrv_noshow_flg = 1 THEN 1 ELSE 0 END) AS "No-show",
    SUM(CASE WHEN r.rsrv_status='Cancelled' AND r.rsrv_status_extended='Cancellation by Customer' THEN 1 ELSE 0 END) AS "Canc. cliente",
    SUM(CASE WHEN r.rsrv_status='Cancelled' AND r.rsrv_status_extended='Cancellation by Sixt' THEN 1 ELSE 0 END) AS "Canc. Sixt"
FROM fact_reservations r
WHERE r.rsrv_handover_date BETWEEN ? AND ? {where_brnc_h}
GROUP BY DATE(r.rsrv_handover_date)
ORDER BY fecha
"""
dem_trend = load_query(dem_trend_sql, (fi.isoformat(), ff.isoformat()))

if not dem_trend.empty:
    melt = dem_trend.melt(id_vars=["fecha"], var_name="Estado", value_name="Reservas")
    fig = px.bar(
        melt, x="fecha", y="Reservas", color="Estado", barmode="stack",
        title="Demanda diaria por estado de reserva (clic en la leyenda para aislar)",
        color_discrete_map={
            "Procesadas": SIXT_ORANGE,
            "No-show": "#666",
            "Canc. cliente": "#d32f2f",
            "Canc. Sixt": SIXT_BLACK,
        },
    )
    fig.update_layout(**PLOTLY_LAYOUT, legend=dict(orientation="h", y=-0.2))
    st.plotly_chart(fig, use_container_width=True)

# =============================================================================
# 3. OCUPACION HISTORICA REAL - calculada por rango de fechas escogido
# =============================================================================
section("Ocupacion historica diaria")

# La tabla vw_cierre_diario_sede ya tiene cier_vehicles_rented (HISTORICO,
# overlap rentals por dia x sede actual del vehiculo) y cier_vehicles_in_branch.
# Para "Todas las sedes" agregamos por dia (suma); para una sede, leemos directo.
ocup_sql = f"""
SELECT cier_date AS fecha,
       SUM(cier_vehicles_in_branch) AS flota,
       SUM(cier_vehicles_rented) AS rentados,
       SUM(cier_vehicles_available) AS disponibles
FROM vw_cierre_diario_sede c
WHERE c.cier_date BETWEEN ? AND ? {where_brnc_c}
GROUP BY cier_date
ORDER BY cier_date
"""
ocup = load_query(ocup_sql, (fi.isoformat(), ff.isoformat()))

if not ocup.empty:
    ocup["ocupacion_pct"] = ocup["rentados"] * 100.0 / ocup["flota"].replace(0, 1)
    avg_pct = ocup["ocupacion_pct"].mean()
    avg_flota = ocup["flota"].mean()

    c1, c2, c3, c4 = st.columns(4)
    kpi(c1, "Flota promedio", f"{avg_flota:.0f}")
    kpi(c2, "Rentados (max)", fmt_int(ocup["rentados"].max()))
    kpi(c3, "Rentados (promedio)", f"{ocup['rentados'].mean():.1f}")
    kpi(c4, "Ocupacion promedio", f"{avg_pct:.1f} %")

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=ocup["fecha"], y=ocup["ocupacion_pct"],
        mode="lines", line=dict(color=SIXT_ORANGE, width=3),
        name="Ocupacion %",
    ))
    fig.update_layout(
        title="Ocupacion diaria (% de flota en renta)",
        **PLOTLY_LAYOUT, yaxis=dict(ticksuffix=" %"),
    )
    st.plotly_chart(fig, use_container_width=True)

st.caption(
    "Numerador: vehiculos asignados a la sede HOY que estaban en un rental abierto ese dia "
    "(overlap handover <= fecha <= return). Denominador: flota actual de la sede (snapshot). "
    "La aproximacion usa la sede actual del vehiculo, no su sede historica; para "
    "volumenes Trust (~106 vehiculos, 6 sedes) es razonable."
)

# =============================================================================
# 3b. CARROS DISPONIBLES POR SEDE Y POR DIA
# =============================================================================
section("Carros disponibles por sede x dia")

if brnc_code is None:
    disp_sql = """
    SELECT c.cier_date AS fecha,
           b.brnc_name AS sede,
           c.cier_vehicles_in_branch AS flota,
           c.cier_vehicles_rented AS rentados,
           c.cier_reservations_pending AS reservas_pendientes,
           c.cier_vehicles_available AS disponibles_fisicos,
           c.cier_vehicles_available_net AS disponibles_netos
    FROM vw_cierre_diario_sede c
    JOIN dim_branches b ON b.brnc_code = c.brnc_code
    WHERE c.cier_date BETWEEN ? AND ?
    ORDER BY c.cier_date, b.brnc_name
    """
    disp = load_query(disp_sql, (fi.isoformat(), ff.isoformat()))
    if not disp.empty:
        # KPIs agregados del periodo
        avg_resv = disp["reservas_pendientes"].sum() / disp["fecha"].nunique() if disp["fecha"].nunique() else 0
        c1, c2, c3 = st.columns(3)
        kpi(c1, "Disponibles fisicos promedio", f"{disp['disponibles_fisicos'].mean():.1f}",
            "= flota - rentados")
        kpi(c2, "Reservas pendientes promedio", f"{avg_resv:.1f}",
            "Open con handover en el dia")
        kpi(c3, "Disponibles netos promedio", f"{disp['disponibles_netos'].mean():.1f}",
            "= flota - rentados - reservas")

        c1, c2 = st.columns(2)
        with c1:
            fig = px.line(
                disp, x="fecha", y="disponibles_netos", color="sede",
                title="Vehiculos disponibles netos por sede (clic en leyenda para aislar)",
            )
            fig.update_layout(**PLOTLY_LAYOUT, legend=dict(orientation="h", y=-0.2))
            st.plotly_chart(fig, use_container_width=True)
        with c2:
            pivot = disp.pivot_table(
                index="sede", columns="fecha", values="disponibles_netos", fill_value=0,
            )
            fig = px.imshow(
                pivot, aspect="auto",
                color_continuous_scale=[[0, "#d32f2f"], [0.5, "#f7f7f7"], [1, SIXT_ORANGE]],
                title="Heatmap disponibles netos por sede x fecha",
            )
            fig.update_layout(**PLOTLY_LAYOUT)
            st.plotly_chart(fig, use_container_width=True)
else:
    disp_sql = """
    SELECT c.cier_date AS fecha,
           c.cier_vehicles_in_branch AS flota,
           c.cier_vehicles_rented AS rentados,
           c.cier_reservations_pending AS reservas_pendientes,
           c.cier_vehicles_available AS disponibles_fisicos,
           c.cier_vehicles_available_net AS disponibles_netos
    FROM vw_cierre_diario_sede c
    WHERE c.cier_date BETWEEN ? AND ? AND c.brnc_code = ?
    ORDER BY c.cier_date
    """
    disp = load_query(disp_sql, (fi.isoformat(), ff.isoformat(), brnc_code))
    if not disp.empty:
        c1, c2, c3 = st.columns(3)
        kpi(c1, "Disponibles fisicos promedio", f"{disp['disponibles_fisicos'].mean():.1f}",
            "= flota - rentados")
        kpi(c2, "Reservas pendientes promedio", f"{disp['reservas_pendientes'].mean():.1f}",
            "Open con handover en el dia")
        kpi(c3, "Disponibles netos promedio", f"{disp['disponibles_netos'].mean():.1f}",
            "= flota - rentados - reservas")

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=disp["fecha"], y=disp["flota"], name="Flota total",
            line=dict(color="#999", width=1, dash="dash"),
        ))
        fig.add_trace(go.Scatter(
            x=disp["fecha"], y=disp["rentados"], name="Rentados",
            line=dict(color=SIXT_BLACK, width=2, dash="dot"),
        ))
        fig.add_trace(go.Scatter(
            x=disp["fecha"], y=disp["reservas_pendientes"], name="Reservas pendientes",
            line=dict(color="#666", width=2, dash="dashdot"),
        ))
        fig.add_trace(go.Scatter(
            x=disp["fecha"], y=disp["disponibles_fisicos"], name="Disponibles fisicos",
            line=dict(color="#999", width=2),
        ))
        fig.add_trace(go.Scatter(
            x=disp["fecha"], y=disp["disponibles_netos"], name="Disponibles netos",
            line=dict(color=SIXT_ORANGE, width=3),
        ))
        fig.update_layout(
            title=f"{brnc_name} - composicion diaria de la flota",
            **PLOTLY_LAYOUT, legend=dict(orientation="h", y=-0.2),
        )
        st.plotly_chart(fig, use_container_width=True)

st.caption(
    "Disponibles fisicos = flota - rentals abiertos ese dia. "
    "Disponibles netos = flota - rentals abiertos - reservas Open con handover ese dia "
    "(reservas que aun no se concretaron en rental ni se cancelaron). "
    "Para planificar capacidad real considere los netos."
)

# =============================================================================
# 4. RENTA POR DIA POR CATEGORIA
# =============================================================================
section("Renta por dia por categoria de vehiculo")

cat_sql = f"""
SELECT COALESCE(vg.vhgr_category_level2, '(sin grupo)') AS categoria,
       COUNT(r.rntl_mvnr) AS rentals,
       COALESCE(SUM(r.rntl_rental_days), 0) AS dias_total,
       COALESCE(SUM(r.rntl_revenue_main_local), 0) AS rev_base,
       COALESCE(SUM(r.rntl_revenue_secondary_local), 0) AS rev_extras,
       COALESCE(SUM(r.rntl_revenue_local_currency), 0) AS rev_total,
       CAST(COALESCE(SUM(r.rntl_revenue_main_local) * 1.0
            / NULLIF(SUM(r.rntl_rental_days), 0), 0) AS REAL) AS price_per_day
FROM fact_rentals r
LEFT JOIN dim_vehicle_groups vg ON vg.vhgr_crs = r.vhgr_crs
WHERE r.rntl_handover_date BETWEEN ? AND ? {where_brnc_h}
GROUP BY categoria
HAVING SUM(r.rntl_rental_days) > 0
ORDER BY price_per_day DESC
"""
cat = load_query(cat_sql, (fi.isoformat(), ff.isoformat()))

if not cat.empty:
    c1, c2 = st.columns(2)
    with c1:
        fig = px.bar(
            cat, x="categoria", y="price_per_day",
            color_discrete_sequence=[SIXT_ORANGE],
            title="Tarifa promedio por dia (COP / dia, base)",
            text="price_per_day",
        )
        fig.update_traces(texttemplate="$ %{text:,.0f}", textposition="outside")
        fig.update_layout(**PLOTLY_LAYOUT, yaxis_tickformat=",.0f")
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        # Mix de revenue
        fig = px.bar(
            cat, x="categoria", y="rev_total",
            color_discrete_sequence=[SIXT_BLACK],
            title="Revenue total por categoria (COP)",
            text="rev_total",
        )
        fig.update_traces(texttemplate="$ %{text:,.0f}", textposition="outside")
        fig.update_layout(**PLOTLY_LAYOUT, yaxis_tickformat=",.0f")
        st.plotly_chart(fig, use_container_width=True)

    # Tabla
    cat_show = cat.copy()
    cat_show["rev_base"] = cat_show["rev_base"].apply(fmt_cop)
    cat_show["rev_extras"] = cat_show["rev_extras"].apply(fmt_cop)
    cat_show["rev_total"] = cat_show["rev_total"].apply(fmt_cop)
    cat_show["price_per_day"] = cat_show["price_per_day"].apply(fmt_cop)
    cat_show["rentals"] = cat_show["rentals"].apply(fmt_int)
    cat_show["dias_total"] = cat_show["dias_total"].apply(fmt_int)
    st.dataframe(
        cat_show.rename(columns={
            "categoria": "Categoria", "rentals": "Rentals", "dias_total": "Dias rental",
            "rev_base": "Revenue base", "rev_extras": "Revenue extras",
            "rev_total": "Revenue total", "price_per_day": "Tarifa / dia",
        }),
        use_container_width=True, hide_index=True,
    )

# =============================================================================
# 5. INGRESOS: BASE vs EXTRAS (por dia)
# =============================================================================
section("Composicion de ingresos: tarifa base vs extras")

ing_sql = f"""
SELECT DATE(r.rntl_handover_date) AS fecha,
       COALESCE(SUM(r.rntl_revenue_main_local), 0) AS "Tarifa base",
       COALESCE(SUM(r.rntl_revenue_secondary_local), 0) AS "Extras"
FROM fact_rentals r
WHERE r.rntl_handover_date BETWEEN ? AND ? {where_brnc_h}
GROUP BY DATE(r.rntl_handover_date)
ORDER BY fecha
"""
ing = load_query(ing_sql, (fi.isoformat(), ff.isoformat()))

if not ing.empty:
    total_base = ing["Tarifa base"].sum()
    total_extras = ing["Extras"].sum()
    pct_extras = (total_extras / (total_base + total_extras) * 100) if (total_base + total_extras) else 0

    c1, c2, c3 = st.columns(3)
    kpi(c1, "Tarifa base (revenue principal)", fmt_cop(total_base), fmt_cop_short(total_base))
    kpi(c2, "Extras (cargos secundarios)", fmt_cop(total_extras), fmt_cop_short(total_extras))
    kpi(c3, "% extras del total", f"{pct_extras:.2f} %")

    melt = ing.melt(id_vars=["fecha"], var_name="Componente", value_name="COP")
    fig = px.bar(
        melt, x="fecha", y="COP", color="Componente", barmode="stack",
        title="Revenue diario apilado por componente (COP)",
        color_discrete_map={"Tarifa base": SIXT_ORANGE, "Extras": SIXT_BLACK},
    )
    fig.update_layout(**PLOTLY_LAYOUT, yaxis_tickformat=",.0f", legend=dict(orientation="h", y=-0.2))
    st.plotly_chart(fig, use_container_width=True)

st.caption(
    "Tarifa base = rntl_revenue_main_local (tarifa pura del rental). "
    "Extras = rntl_revenue_secondary_local (cobros adicionales: addons, cobertura, conductor extra, etc.). "
    "Para detalle granular por tipo de cargo ver fact_charges_ra (codigos chra_chco)."
)

# =============================================================================
# 6. FLOTA POR SEDE Y CATEGORIA (snapshot actual)
# =============================================================================
section("Flota actual por sede y categoria")

flota_sql = f"""
SELECT b.brnc_name AS sede,
       COALESCE(vg.vhgr_category_level2, '(sin grupo)') AS categoria,
       COUNT(*) AS total,
       SUM(CASE WHEN vc.vhcl_on_rent_flg = 1 THEN 1 ELSE 0 END) AS rentados,
       SUM(CASE WHEN vc.vhcl_ready_to_rent_flg = 1 AND vc.vhcl_on_rent_flg = 0 THEN 1 ELSE 0 END) AS disponibles,
       SUM(CASE WHEN vc.vhcl_ready_to_rent_flg = 0 AND vc.vhcl_on_rent_flg = 0 THEN 1 ELSE 0 END) AS otros
FROM dim_vehicles_current vc
LEFT JOIN dim_branches b ON b.brnc_code = vc.brnc_code
LEFT JOIN dim_vehicles v ON v.vhcl_int_num = vc.vhcl_int_num
LEFT JOIN dim_vehicle_groups vg ON vg.vhgr_crs = v.vhgr_crs
WHERE 1=1 {where_brnc_v}
GROUP BY sede, categoria
ORDER BY sede, categoria
"""
flota_df = load_query(flota_sql)

if not flota_df.empty:
    c1, c2 = st.columns(2)

    # Heatmap disponibles por sede x categoria
    with c1:
        pivot_disp = flota_df.pivot_table(
            index="sede", columns="categoria", values="disponibles", fill_value=0,
        )
        fig = px.imshow(
            pivot_disp, aspect="auto", text_auto=True,
            color_continuous_scale=[[0, "#f7f7f7"], [1, SIXT_ORANGE]],
            title="Vehiculos DISPONIBLES por sede y categoria",
        )
        fig.update_layout(**PLOTLY_LAYOUT)
        st.plotly_chart(fig, use_container_width=True)

    # Stacked bar: estado por sede
    with c2:
        sede_state = flota_df.groupby("sede", as_index=False).agg(
            Rentados=("rentados", "sum"),
            Disponibles=("disponibles", "sum"),
            Otros=("otros", "sum"),
        )
        melt = sede_state.melt(id_vars=["sede"], var_name="Estado", value_name="Vehiculos")
        fig = px.bar(
            melt, x="sede", y="Vehiculos", color="Estado", barmode="stack",
            title="Estado de la flota por sede",
            color_discrete_map={"Rentados": SIXT_ORANGE, "Disponibles": "#999", "Otros": SIXT_BLACK},
        )
        fig.update_layout(**PLOTLY_LAYOUT, legend=dict(orientation="h", y=-0.2))
        st.plotly_chart(fig, use_container_width=True)

    # Tabla
    st.dataframe(
        flota_df.rename(columns={
            "sede": "Sede", "categoria": "Categoria", "total": "Total",
            "rentados": "Rentados", "disponibles": "Disponibles", "otros": "Otros",
        }),
        use_container_width=True, hide_index=True,
    )

st.caption(
    "Snapshot del estado actual de la flota (dim_vehicles_current). "
    "Cuando hay disponibles fuera de la sede de mayor demanda, considerar traslado inter-sede."
)

# =============================================================================
# 7. TENDENCIA DIARIA (con hue por sede cuando 'todas las sedes')
# =============================================================================
section("Tendencia diaria del periodo")

if brnc_code is None:
    trend_sql = """
    SELECT c.cier_date AS fecha,
           b.brnc_name AS sede,
           SUM(c.cier_rentals_count) AS rentals,
           SUM(c.cier_revenue_total) AS revenue
    FROM vw_cierre_diario_sede c
    JOIN dim_branches b ON b.brnc_code = c.brnc_code
    WHERE c.cier_date BETWEEN ? AND ?
    GROUP BY c.cier_date, b.brnc_name
    ORDER BY c.cier_date, b.brnc_name
    """
    trend = load_query(trend_sql, (fi.isoformat(), ff.isoformat()))
    if trend.empty:
        st.info("No hay actividad para los filtros seleccionados.")
    else:
        c1, c2 = st.columns(2)
        with c1:
            fig = px.line(
                trend, x="fecha", y="rentals", color="sede",
                title="Rentals por sede (clic en la leyenda para aislar)",
            )
            fig.update_layout(**PLOTLY_LAYOUT, legend=dict(orientation="h", y=-0.2))
            st.plotly_chart(fig, use_container_width=True)
        with c2:
            fig = px.bar(
                trend, x="fecha", y="revenue", color="sede", barmode="stack",
                title="Revenue diario apilado por sede (COP)",
            )
            fig.update_layout(**PLOTLY_LAYOUT, yaxis_tickformat=",.0f", legend=dict(orientation="h", y=-0.2))
            st.plotly_chart(fig, use_container_width=True)
else:
    trend_sql = f"""
    SELECT c.cier_date AS fecha,
           SUM(c.cier_rentals_count) AS rentals,
           SUM(c.cier_returns_count) AS returns,
           SUM(c.cier_revenue_total) AS revenue
    FROM vw_cierre_diario_sede c
    WHERE c.cier_date BETWEEN ? AND ? {where_brnc_c}
    GROUP BY c.cier_date
    ORDER BY c.cier_date
    """
    trend = load_query(trend_sql, (fi.isoformat(), ff.isoformat()))
    if trend.empty:
        st.info("No hay actividad para los filtros seleccionados.")
    else:
        c1, c2 = st.columns(2)
        with c1:
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=trend["fecha"], y=trend["rentals"], name="Rentals",
                                     line=dict(color=SIXT_ORANGE, width=3)))
            fig.add_trace(go.Scatter(x=trend["fecha"], y=trend["returns"], name="Devoluciones",
                                     line=dict(color=SIXT_BLACK, width=2, dash="dot")))
            fig.update_layout(title="Rentals vs Devoluciones por dia", **PLOTLY_LAYOUT)
            st.plotly_chart(fig, use_container_width=True)
        with c2:
            fig = px.bar(trend, x="fecha", y="revenue", color_discrete_sequence=[SIXT_ORANGE],
                         title="Revenue diario (COP)")
            fig.update_layout(**PLOTLY_LAYOUT, yaxis_tickformat=",.0f")
            st.plotly_chart(fig, use_container_width=True)

# =============================================================================
# 8. DETALLE: SEDE x DIA
# =============================================================================
section("Detalle: sede x dia")
detalle_sql = f"""
SELECT c.cier_date AS Fecha,
       b.brnc_name AS Sede,
       c.cier_rentals_count AS Rentals,
       c.cier_returns_count AS Devoluciones,
       c.cier_revenue_total AS Revenue,
       c.cier_vehicles_in_branch AS Flota,
       c.cier_vehicles_rented AS Rentadas,
       c.cier_vehicles_available AS Disponibles
FROM vw_cierre_diario_sede c
JOIN dim_branches b ON b.brnc_code = c.brnc_code
WHERE c.cier_date BETWEEN ? AND ? {where_brnc_c}
ORDER BY c.cier_date DESC, b.brnc_name
LIMIT 1000
"""
df = load_query(detalle_sql, (fi.isoformat(), ff.isoformat()))
if not df.empty:
    df["Revenue"] = df["Revenue"].apply(fmt_cop)
st.dataframe(df, use_container_width=True, hide_index=True, height=420)

st.caption(
    "Reporte completo construido sobre Tramo 1 (reservas + rentals + flota). "
    "Refresh automatico cada 6 horas via pipeline Bronze->Silver."
)
