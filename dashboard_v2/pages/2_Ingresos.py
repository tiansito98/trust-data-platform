"""
Ingresos - Objetivo 2 del dashboard v2.

Tarifa (codigo T) vs adicionales (CONTEXTO, COBERTURA, EXTRA, AJUSTE,
PENALIZACION, OTROS) por sede. Drilldown por categoria y por codigo de
cargo (T, BF, SL, Y, AD, etc.).

Fuente: vw_rentals_resumen para los totales / mix, vw_rentals_detail para
el desglose por codigo. Toda la logica de tarifa-vs-adicional vive en
silver (dim_charge_types.categoria); el dashboard solo agrupa.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

from components.common import (
    inject_styles, render_header, section, kpi, fmt_money, fmt_money_short,
    fmt_int, fmt_pct, load_query, apply_trm,
    PLOTLY_LAYOUT, SIXT_ORANGE, SIXT_BLACK,
)
from components.filters import render_sidebar_filters, render_active_filters_banner
from components.auth import require_auth, logout_button

st.set_page_config(page_title="Trust v2 - Ingresos", layout="wide")
require_auth()
inject_styles()
logout_button()
render_header("Ingresos: Tarifa vs Adicionales")

filtros = render_sidebar_filters(default_days=30, show_canal=True)
render_active_filters_banner(filtros)

where_sql, params = filtros.where_clause()
suf = "_usd" if filtros.moneda == "USD" else "_cop"
cur = filtros.moneda

# ---------- KPIs principales ----------
tot_sql = f"""
SELECT COUNT(*) AS rentals,
       COALESCE(SUM(tarifa_usd), 0)        AS tarifa_usd,
       COALESCE(SUM(adicionales_usd), 0)   AS adicionales_usd,
       COALESCE(SUM(descuento_usd), 0)     AS descuento_usd,
       COALESCE(SUM(neto_usd), 0)          AS neto_usd,
       COALESCE(SUM(tarifa_cop), 0)        AS tarifa_cop,
       COALESCE(SUM(adicionales_cop), 0)   AS adicionales_cop,
       COALESCE(SUM(descuento_cop), 0)     AS descuento_cop,
       COALESCE(SUM(neto_cop), 0)          AS neto_cop,
       MIN(DATE(fecha_handover_real))      AS d_min,
       MAX(DATE(fecha_handover_real))      AS d_max
FROM vw_rentals_resumen
WHERE {where_sql}
"""
tot = load_query(tot_sql, params).iloc[0]

# Recalcular COP si Banrep (escalar por TRM promedio del rango es inexacto;
# para los KPIs cabecera tomamos directo el SUM USD y multiplicamos por TRM
# promedio del rango. Mejor: agregamos un df pequeno y aplicamos apply_trm.
# Pero para el header usamos solo USD para evitar TRM agregada).
tarifa_usd = float(tot["tarifa_usd"])
adic_usd = float(tot["adicionales_usd"])
neto_usd = float(tot["neto_usd"])
mix_pct = (adic_usd / (tarifa_usd + adic_usd) * 100) if (tarifa_usd + adic_usd) else 0

c1, c2, c3, c4 = st.columns(4)
kpi(c1, "Rentals", fmt_int(tot["rentals"]))
kpi(c2, "Tarifa (T)", fmt_money(tarifa_usd, "USD"), fmt_money_short(tarifa_usd, "USD"))
kpi(c3, "Adicionales", fmt_money(adic_usd, "USD"), fmt_money_short(adic_usd, "USD"))
kpi(c4, "% Adicionales", f"{mix_pct:.1f} %",
    f"Sobre tarifa+adic. Neto {fmt_money_short(neto_usd, 'USD')}")

st.caption(
    "Los KPIs y graficas USD son nativos del datashare. Cuando seleccionas COP, "
    "se aplican las columnas paralelas del view (TRM Sixt) o se recalcula USDxTRM "
    "Banrep por fila segun el toggle."
)

# ---------- Mix tarifa vs adicionales por sede ----------
section("Mix por sede")
mix_sql = f"""
SELECT sede_handover,
       SUM(tarifa_usd)        AS tarifa_usd,
       SUM(adicionales_usd)   AS adicionales_usd,
       SUM(tarifa_cop)        AS tarifa_cop,
       SUM(adicionales_cop)   AS adicionales_cop,
       COUNT(*)               AS rentals
FROM vw_rentals_resumen
WHERE {where_sql}
GROUP BY sede_handover
ORDER BY tarifa_usd DESC
"""
df_sede = load_query(mix_sql, params)

if df_sede.empty:
    st.info("Sin datos para los filtros seleccionados.")
else:
    for c in ["tarifa_usd", "adicionales_usd", "tarifa_cop", "adicionales_cop"]:
        df_sede[c] = pd.to_numeric(df_sede[c], errors="coerce").fillna(0.0)
    denom = (df_sede[f"tarifa{suf}"] + df_sede[f"adicionales{suf}"]).replace(0, np.nan)
    df_sede["pct_adic"] = (df_sede[f"adicionales{suf}"] / denom * 100).fillna(0).round(1)

    melted = df_sede.melt(
        id_vars=["sede_handover", "pct_adic", "rentals"],
        value_vars=[f"tarifa{suf}", f"adicionales{suf}"],
        var_name="componente", value_name="monto",
    )
    melted["componente"] = melted["componente"].map(
        {f"tarifa{suf}": "Tarifa", f"adicionales{suf}": "Adicionales"}
    )

    c_left, c_right = st.columns([3, 2])
    with c_left:
        fig = px.bar(
            melted, x="sede_handover", y="monto", color="componente",
            barmode="stack",
            title=f"Tarifa vs adicionales por sede ({cur})",
            color_discrete_map={"Tarifa": SIXT_ORANGE, "Adicionales": SIXT_BLACK},
        )
        fig.update_layout(**PLOTLY_LAYOUT, yaxis_tickformat=",.0f",
                          xaxis_title="", yaxis_title=cur,
                          legend=dict(orientation="h", y=-0.2))
        st.plotly_chart(fig, use_container_width=True)

    with c_right:
        view = df_sede[["sede_handover", "rentals",
                        f"tarifa{suf}", f"adicionales{suf}", "pct_adic"]].copy()
        view[f"tarifa{suf}"] = view[f"tarifa{suf}"].apply(lambda v: fmt_money(v, cur))
        view[f"adicionales{suf}"] = view[f"adicionales{suf}"].apply(lambda v: fmt_money(v, cur))
        view["pct_adic"] = view["pct_adic"].apply(lambda v: f"{v:.1f} %")
        view = view.rename(columns={
            "sede_handover": "Sede",
            "rentals": "Rentals",
            f"tarifa{suf}": f"Tarifa ({cur})",
            f"adicionales{suf}": f"Adicionales ({cur})",
            "pct_adic": "% Adic",
        })
        st.dataframe(view, use_container_width=True, hide_index=True)

# ---------- Revenue por categoria de cargo ----------
section("Revenue por categoria de cargo")
st.caption(
    "Categorias del datashare: TARIFA (codigo T), CONTEXTO (location fee, "
    "airport fee...), COBERTURA (BF, SL, CDW), EXTRA (silla, GPS, AD), "
    "AJUSTE (descuentos no contractuales, redondeos), PENALIZACION "
    "(combustible faltante, abandono), OTROS."
)
cat_sql = f"""
SELECT d.cargo_categoria,
       COUNT(*)                              AS cargos,
       COUNT(DISTINCT d.numero_contrato)     AS contratos,
       SUM(d.subtotal_usd)                   AS suma_usd
FROM vw_rentals_detail d
WHERE d.fuente_cargo = 'RENTAL_COUNTER'
  AND d.rental_currency = 'USD'
  AND DATE(d.fecha_handover_real) BETWEEN ? AND ?
"""
cat_params = [filtros.fecha_desde.isoformat(), filtros.fecha_hasta.isoformat()]
if filtros.sedes_codigos:
    placeholders = ",".join("?" * len(filtros.sedes_codigos))
    cat_sql += f" AND d.sede_handover_codigo IN ({placeholders}) "
    cat_params.extend(filtros.sedes_codigos)
if filtros.acriss:
    placeholders = ",".join("?" * len(filtros.acriss))
    cat_sql += f" AND d.acriss_entregado IN ({placeholders}) "
    cat_params.extend(filtros.acriss)
cat_sql += " GROUP BY d.cargo_categoria ORDER BY suma_usd DESC"
df_cat = load_query(cat_sql, tuple(cat_params))
if not df_cat.empty:
    for c in ["cargos", "contratos", "suma_usd"]:
        df_cat[c] = pd.to_numeric(df_cat[c], errors="coerce").fillna(0.0)

if not df_cat.empty:
    c1, c2 = st.columns([2, 3])
    with c1:
        fig = px.pie(
            df_cat, names="cargo_categoria", values="suma_usd",
            title=f"Distribucion (USD)",
            color_discrete_sequence=[SIXT_ORANGE, SIXT_BLACK,
                                     "#666666", "#999999", "#cccccc",
                                     "#ffaa66", "#ffd1a8"],
        )
        fig.update_layout(**PLOTLY_LAYOUT)
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        view = df_cat.copy()
        view["suma_usd"] = view["suma_usd"].apply(lambda v: fmt_money(v, "USD"))
        view = view.rename(columns={
            "cargo_categoria": "Categoria",
            "cargos": "Cargos",
            "contratos": "Contratos",
            "suma_usd": "Revenue (USD)",
        })
        st.dataframe(view, use_container_width=True, hide_index=True)

# ---------- Top codigos de adicionales ----------
section("Top codigos de cargo (todos)")
top_sql = cat_sql.replace(
    "SELECT d.cargo_categoria,",
    "SELECT d.cargo_categoria, d.cargo_codigo, d.cargo_descripcion,"
).replace(
    "GROUP BY d.cargo_categoria",
    "GROUP BY d.cargo_categoria, d.cargo_codigo, d.cargo_descripcion"
)
df_top = load_query(top_sql, tuple(cat_params))
if not df_top.empty:
    for c in ["cargos", "contratos", "suma_usd"]:
        df_top[c] = pd.to_numeric(df_top[c], errors="coerce").fillna(0.0)

if not df_top.empty:
    # Top 20 por revenue.
    df_top = df_top.sort_values("suma_usd", ascending=False).head(20).reset_index(drop=True)
    df_top["pct_total"] = (
        df_top["suma_usd"] / df_top["suma_usd"].sum() * 100
    ).round(1)

    fig = px.bar(
        df_top, y="cargo_codigo", x="suma_usd", color="cargo_categoria",
        orientation="h",
        title="Top 20 codigos por revenue (USD)",
        hover_data=["cargo_descripcion", "cargos"],
        color_discrete_sequence=[SIXT_ORANGE, SIXT_BLACK,
                                 "#666666", "#999999", "#cccccc",
                                 "#ffaa66", "#ffd1a8"],
    )
    fig.update_layout(**PLOTLY_LAYOUT, xaxis_tickformat=",.0f",
                      yaxis=dict(autorange="reversed"))
    st.plotly_chart(fig, use_container_width=True)

    view = df_top.copy()
    view["suma_usd"] = view["suma_usd"].apply(lambda v: fmt_money(v, "USD"))
    view["pct_total"] = view["pct_total"].apply(lambda v: f"{v:.1f} %")
    view = view.rename(columns={
        "cargo_codigo": "Cod",
        "cargo_descripcion": "Descripcion",
        "cargo_categoria": "Categoria",
        "cargos": "Cargos",
        "contratos": "Contratos",
        "suma_usd": "Revenue (USD)",
        "pct_total": "% del top 20",
    })
    st.dataframe(view, use_container_width=True, hide_index=True)
