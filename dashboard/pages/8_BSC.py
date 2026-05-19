"""BSC - Balanced Scorecard mensual / por periodo configurable.

Cubre los 7 KPIs derivables hoy de Silver. Los 3 KPIs que requieren fuente
externa (Forecast Error, RPD vs recomendado, GOPPAC) se listan al final como
'pendientes de fuente externa' con explicacion.
"""
import sys
import datetime as dt
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from components.common import (
    inject_styles, render_header, render_active_filters, kpi, kpi_bsc, section,
    branch_filter,
    load_query, fmt_int, fmt_cop, fmt_cop_short,
    bsc_status, bsc_status_range,
    PLOTLY_LAYOUT, SIXT_ORANGE, SIXT_BLACK,
)

st.set_page_config(page_title="BSC - Trust", layout="wide")
inject_styles()
render_header("Balanced Scorecard - Comite Operativo")


# =============================================================================
# Sidebar: filtros propios de la pagina
# =============================================================================
with st.sidebar:
    st.markdown("## Filtros")
    brnc_code, brnc_name = branch_filter()

    period_options = [
        "Ultimo dia",
        "Ultima semana",
        "Ultimo mes",
        "Ultimos 3 meses",
        "Ultimos 12 meses",
        "Personalizado",
    ]
    period = st.radio("Periodo", period_options, index=2, key="bsc_period")


def _today_clipped():
    """Hoy real, pero clipped al maximo de dim_dates."""
    row = load_query(
        "SELECT MAX(full_date) AS d FROM dim_dates WHERE full_date <= DATE('now')"
    )
    s = row["d"].iloc[0] if len(row) and row["d"].iloc[0] else None
    return dt.date.fromisoformat(s) if s else dt.date.today()


_today = _today_clipped()

if period == "Ultimo dia":
    fi, ff = _today, _today
elif period == "Ultima semana":
    fi, ff = _today - dt.timedelta(days=7), _today
elif period == "Ultimo mes":
    fi, ff = _today - dt.timedelta(days=30), _today
elif period == "Ultimos 3 meses":
    fi, ff = _today - dt.timedelta(days=90), _today
elif period == "Ultimos 12 meses":
    fi, ff = _today - dt.timedelta(days=365), _today
else:
    # Personalizado
    with st.sidebar:
        custom = st.date_input(
            "Rango personalizado",
            value=(_today - dt.timedelta(days=30), _today),
            key="bsc_custom_dates",
        )
    if isinstance(custom, tuple) and len(custom) == 2:
        fi, ff = custom
    else:
        fi, ff = _today - dt.timedelta(days=30), _today

render_active_filters(brnc_name, fi, ff, extra=f"<strong>Preset:</strong> {period}")
ndias = (ff - fi).days + 1

# Filtros de SQL parametrizables
where_brnc_h = "" if brnc_code is None else f" AND r.brnc_code_handover = {brnc_code} "
where_brnc_c = "" if brnc_code is None else f" AND c.brnc_code = {brnc_code} "


# =============================================================================
# DEMANDA
# =============================================================================
section("Perspectiva: Demanda")

dem_sql = f"""
SELECT
    COUNT(*) AS total,
    SUM(CASE WHEN r.rsrv_status='Processed' AND r.rsrv_status_extended='Invoice' THEN 1 ELSE 0 END) AS procesadas,
    SUM(CASE WHEN r.rsrv_status='Cancelled' AND r.rsrv_status_extended='Cancellation by Sixt' THEN 1 ELSE 0 END) AS canc_sixt,
    SUM(CASE WHEN r.rsrv_noshow_flg = 1 THEN 1 ELSE 0 END) AS no_show,
    SUM(CASE WHEN r.rsrv_cancelled_flg = 1 THEN 1 ELSE 0 END) AS canceladas,
    SUM(CASE WHEN r.rsrv_status IN ('Processed', 'Cancelled') OR r.rsrv_noshow_flg=1 THEN 1 ELSE 0 END) AS confirmadas
FROM fact_reservations r
WHERE r.rsrv_handover_date BETWEEN ? AND ? {where_brnc_h}
"""
d = load_query(dem_sql, (fi.isoformat(), ff.isoformat())).iloc[0]
total_d = d["total"] or 0

served_pct = (d["procesadas"] / total_d * 100) if total_d else None
lost_pct = ((d["canc_sixt"] + d["no_show"]) / total_d * 100) if total_d else None
cancel_rate = (d["canceladas"] / d["confirmadas"] * 100) if d["confirmadas"] else None

c1, c2, c3, c4 = st.columns(4)
kpi(c1, "Demanda total (reservas)", fmt_int(total_d), f"{ndias} dias del periodo")

# Served % - aproximado (sin "calificada" estricta)
kpi_bsc(
    c2, "Served % (aprox)", f"{served_pct:.1f} %" if served_pct is not None else "—",
    status=bsc_status(served_pct, green=95, yellow=92, comparator=">="),
    target="Meta: >= 95% verde, >= 92% amarillo",
)

# Lost % - canc_sixt + no_show / total
kpi_bsc(
    c3, "Lost % (aprox)", f"{lost_pct:.1f} %" if lost_pct is not None else "—",
    status=bsc_status(lost_pct, green=3, yellow=5, comparator="<="),
    target="Meta: <= 3% verde, <= 5% amarillo",
)

# Cancel Rate
kpi_bsc(
    c4, "Cancel Rate", f"{cancel_rate:.1f} %" if cancel_rate is not None else "—",
    status=bsc_status(cancel_rate, green=4, yellow=6, comparator="<="),
    target="Meta: <= 4% verde, <= 6% amarillo",
)

st.caption(
    "**Served %** = Procesadas/total reservas. Sin info de 'calificada' fina. "
    "**Lost %** = (canceladas por Sixt + no-show)/total — controlables del lado oferta. "
    "Las canceladas por cliente se reportan por separado en Cancel Rate. "
    "**Cancel Rate** = canceladas / (Procesadas + Canceladas + No-show)."
)


# =============================================================================
# CAPACIDAD
# =============================================================================
section("Perspectiva: Capacidad")

cap_sql = f"""
WITH daily AS (
    SELECT
        c.cier_date,
        SUM(c.cier_vehicles_in_branch) AS flota,
        SUM(c.cier_vehicles_rented) AS rentados,
        SUM(c.cier_reservations_pending) AS reservas,
        SUM(c.cier_vehicles_available_net) AS disp_net
    FROM vw_cierre_diario_sede c
    WHERE c.cier_date BETWEEN ? AND ? {where_brnc_c}
    GROUP BY c.cier_date
)
SELECT
    COUNT(*) AS dias_con_data,
    SUM(flota) AS auto_dias_disponibles,
    SUM(rentados) AS auto_dias_rentados,
    SUM(reservas) AS auto_dias_reservados,
    SUM(CASE WHEN disp_net = 0 THEN 1 ELSE 0 END) AS dias_over_demand,
    SUM(CASE WHEN flota > 0 AND rentados * 1.0 / flota < 0.70 THEN 1 ELSE 0 END) AS dias_sub_util
FROM daily
"""
cap = load_query(cap_sql, (fi.isoformat(), ff.isoformat())).iloc[0]

util_pct = (cap["auto_dias_rentados"] / cap["auto_dias_disponibles"] * 100) if cap["auto_dias_disponibles"] else None

# Normalizacion de dias de over-demand y sub-utilizacion: la matriz BSC define
# umbrales mensuales (~30 dias). Si el periodo es mas largo o mas corto,
# normalizamos a "por mes" para comparar contra los semaforos.
def _per_month(value):
    if value is None or ndias == 0:
        return None
    return value * 30.0 / ndias

over_per_month = _per_month(cap["dias_over_demand"])
sub_per_month = _per_month(cap["dias_sub_util"])

c1, c2, c3, c4 = st.columns(4)

kpi_bsc(
    c1, "Utilizacion",
    f"{util_pct:.1f} %" if util_pct is not None else "—",
    status=bsc_status_range(util_pct, green_lo=80, green_hi=88, yellow_lo=70, yellow_hi=92),
    target="Banda optima 80-88%",
)

kpi_bsc(
    c2, "Dias en over-demand (norm. mes)",
    f"{over_per_month:.1f}" if over_per_month is not None else "—",
    status=bsc_status(over_per_month, green=4, yellow=7, comparator="<="),
    target="Meta: <= 4 dias / mes verde",
)

kpi_bsc(
    c3, "Dias en sub-utilizacion (norm. mes)",
    f"{sub_per_month:.1f}" if sub_per_month is not None else "—",
    status=bsc_status(sub_per_month, green=6, yellow=10, comparator="<="),
    target="Meta: <= 6 dias / mes verde (umbral 70%)",
)

kpi(c4, "Dias con data", fmt_int(cap["dias_con_data"]),
    f"sobre {ndias} del periodo")

st.caption(
    "**Utilizacion** = SUM(rentados-dia)/SUM(flota-dia). El denominador incluye TODOS los "
    "dias-auto (no descontamos 'fuera de servicio' porque Sixt no comparte mantenimiento). "
    "Para periodos != 30 dias, los conteos de over-demand y sub-utilizacion se normalizan "
    "linealmente a 'por mes' para poder usar los semaforos de la matriz BSC. "
    "**Over-demand** = dias con disponibles netos = 0 (saturada). "
    "**Sub-utilizacion** = dias con (rentados/flota) < 70%."
)


# =============================================================================
# VALOR
# =============================================================================
section("Perspectiva: Valor")

val_sql = f"""
SELECT
    SUM(c.cier_revenue_total) AS revenue,
    SUM(c.cier_vehicles_in_branch) AS auto_dias_disponibles,
    SUM(c.cier_rentals_count) AS rentals,
    SUM(c.cier_returns_count) AS returns
FROM vw_cierre_diario_sede c
WHERE c.cier_date BETWEEN ? AND ? {where_brnc_c}
"""
v = load_query(val_sql, (fi.isoformat(), ff.isoformat())).iloc[0]

yield_cop = (v["revenue"] / v["auto_dias_disponibles"]) if v["auto_dias_disponibles"] else None
ticket = (v["revenue"] / v["rentals"]) if v["rentals"] else None

# Yield YoY: comparar mismo periodo del año anterior
fi_yoy = fi - dt.timedelta(days=365)
ff_yoy = ff - dt.timedelta(days=365)
val_yoy = load_query(val_sql, (fi_yoy.isoformat(), ff_yoy.isoformat())).iloc[0]
yield_yoy = (val_yoy["revenue"] / val_yoy["auto_dias_disponibles"]) if val_yoy["auto_dias_disponibles"] else None
yoy_delta_pct = ((yield_cop / yield_yoy - 1) * 100) if (yield_cop and yield_yoy) else None

c1, c2, c3, c4 = st.columns(4)

kpi(c1, "Revenue del periodo", fmt_cop(v["revenue"]), fmt_cop_short(v["revenue"]))
kpi(c2, "Ticket promedio", fmt_cop(ticket) if ticket else "—",
    f"{fmt_int(v['rentals'])} rentals")

# Yield = revenue / dias auto disponibles
kpi_bsc(
    c3, "Yield (Revenue / auto / dia)",
    fmt_cop(yield_cop) if yield_cop is not None else "—",
    status="gray",  # sin meta absoluta
    target="Meta: crecimiento >= inflacion + 2pp YoY",
)

# YoY: si delta >= 0 verde; si entre -5% y 0 amarillo; menos de -5% rojo
kpi_bsc(
    c4, "Yield YoY",
    f"{yoy_delta_pct:+.1f} %" if yoy_delta_pct is not None else "—",
    status=bsc_status(yoy_delta_pct, green=0, yellow=-5, comparator=">=") if yoy_delta_pct is not None else "gray",
    target="vs mismo periodo año anterior",
)

st.caption(
    "**Yield** = revenue total / dias-auto-disponibles del periodo. "
    "Mismo caveat que Utilizacion: el denominador no descuenta 'fuera de servicio'. "
    "**Yield YoY** compara con el mismo rango de fechas hace 365 dias para detectar "
    "crecimiento real (ajustando estacionalidad). El semaforo asume que la meta es "
    "crecer al menos sobre la inflacion (no parametrizada aqui)."
)


# =============================================================================
# Tendencia mensual de los KPIs principales
# =============================================================================
section("Tendencia mensual del periodo")

trend_sql = f"""
SELECT
    strftime('%Y-%m', c.cier_date) AS mes,
    SUM(c.cier_rentals_count) AS rentals,
    SUM(c.cier_revenue_total) AS revenue,
    SUM(c.cier_vehicles_rented) * 1.0 / NULLIF(SUM(c.cier_vehicles_in_branch), 0) * 100 AS util_pct,
    SUM(c.cier_revenue_total) * 1.0 / NULLIF(SUM(c.cier_vehicles_in_branch), 0) AS yield_cop
FROM vw_cierre_diario_sede c
WHERE c.cier_date BETWEEN ? AND ? {where_brnc_c}
GROUP BY mes
ORDER BY mes
"""
tr = load_query(trend_sql, (fi.isoformat(), ff.isoformat()))

if not tr.empty and len(tr) > 1:
    c1, c2 = st.columns(2)
    with c1:
        fig = px.line(
            tr, x="mes", y="util_pct", markers=True,
            title="Utilizacion mensual (%)",
            color_discrete_sequence=[SIXT_ORANGE],
        )
        fig.add_hrect(y0=80, y1=88, fillcolor="#2e7d32", opacity=0.08, line_width=0)
        fig.add_hrect(y0=70, y1=80, fillcolor="#f59e0b", opacity=0.08, line_width=0)
        fig.add_hrect(y0=88, y1=92, fillcolor="#f59e0b", opacity=0.08, line_width=0)
        fig.update_layout(**PLOTLY_LAYOUT, yaxis=dict(ticksuffix=" %"))
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        fig = px.bar(
            tr, x="mes", y="yield_cop",
            title="Yield mensual (Revenue / auto / dia, COP)",
            color_discrete_sequence=[SIXT_BLACK],
        )
        fig.update_layout(**PLOTLY_LAYOUT, yaxis_tickformat=",.0f")
        st.plotly_chart(fig, use_container_width=True)
else:
    st.info("Periodo seleccionado tiene menos de 2 meses. Cambie a un rango mas largo para ver tendencia.")


# =============================================================================
# Pendientes de fuente externa
# =============================================================================
section("KPIs pendientes de fuente externa")

st.markdown(
    """
| KPI | Por que no se puede HOY | Que se necesita |
|---|---|---|
| **Forecast Error %** | Trust no carga el forecast comercial-operativo en Silver | Tabla `op_forecast_demanda` con forecast por mes/sede/categoria, cargada via Excel import o forms |
| **RPD real vs recomendado** | No tenemos la tarifa recomendada del pricing engine | Tabla `op_tarifa_recomendada` con tarifa por sede/categoria/dia, exportada del pricing engine |
| **GOPPAC** | Falta el P&L operativo (costos por sede) | Tabla `op_pnl_sede` con GOP mensual por sede, exportada del ERP/contabilidad |

Cuando esas tablas existan, los KPIs se calculan con joins simples sobre `fact_rentals` y `vw_cierre_diario_sede`.
"""
)

st.caption(
    "Esta vista BSC consume datos derivados de Tramo 1 (reservas, rentals, charges). "
    "Los caveats individuales de cada KPI estan en el caption de cada perspectiva. "
    "Para auditoria detallada, los numeros se pueden cruzar con la pagina 'Cierre Diario'."
)
