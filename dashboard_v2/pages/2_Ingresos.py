"""
Ingresos - Objetivo 2 del dashboard v2.

Tarifa (codigo T) vs adicionales (CONTEXTO, COBERTURA, EXTRA, AJUSTE,
PENALIZACION, OTROS) por sede. Drilldown por categoria y por codigo de
cargo (T, BF, SL, Y, AD, etc.).

KPIs incluyen RPD = (Tarifa + Adicionales) / Rentals.

Conversion COP: SIEMPRE recalculada desde USD x TRM Banrep oficial del dia
del handover (apply_trm). Las columnas _cop nativas del view usan la TRM
interna de Sixt y NO se exponen al usuario.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import plotly.express as px
import streamlit as st

from components.common import (
    inject_styles, render_header, section, kpi, fmt_money, fmt_money_short,
    fmt_int, load_query, apply_trm,
    PLOTLY_LAYOUT, SIXT_ORANGE, SIXT_BLACK,
)
from components.filters import render_sidebar_filters, render_active_filters_banner
from components.auth import require_auth, logout_button

st.set_page_config(page_title="TRUST - Ingresos", layout="wide")
require_auth()
inject_styles()
logout_button()
render_header("Ingresos: Tarifa vs Adicionales")

filtros = render_sidebar_filters(default_days=30, show_canal=True)
render_active_filters_banner(filtros)

where_sql, params = filtros.where_clause()
suf = "_usd" if filtros.moneda == "USD" else "_cop"
cur = filtros.moneda


# =============================================================================
# Pull per-rental data (small, ~50-500 rows). Aplicar Banrep TRM si COP.
# Asi los SUMs en pandas reflejan TRM oficial, no la TRM Sixt interna.
# =============================================================================
res_sql = f"""
SELECT numero_contrato, fecha_handover_real, sede_handover, dias_renta,
       COALESCE(tarifa_usd, 0)      AS tarifa_usd,
       COALESCE(adicionales_usd, 0) AS adicionales_usd,
       COALESCE(descuento_usd, 0)   AS descuento_usd,
       COALESCE(neto_usd, 0)        AS neto_usd,
       COALESCE(tarifa_cop, 0)      AS tarifa_cop,
       COALESCE(adicionales_cop, 0) AS adicionales_cop,
       COALESCE(descuento_cop, 0)   AS descuento_cop,
       COALESCE(neto_cop, 0)        AS neto_cop
FROM vw_rentals_resumen
WHERE {where_sql}
"""
df_res = load_query(res_sql, params)
for c in ("tarifa_usd", "adicionales_usd", "descuento_usd", "neto_usd",
          "tarifa_cop", "adicionales_cop", "descuento_cop", "neto_cop",
          "dias_renta"):
    df_res[c] = pd.to_numeric(df_res[c], errors="coerce").fillna(0.0)

# Recalcular columnas _cop con TRM Banrep oficial (sobreescribe la TRM Sixt).
if filtros.moneda == "COP":
    df_res = apply_trm(
        df_res, "Banrep", "fecha_handover_real",
        usd_cols=["tarifa_usd", "adicionales_usd", "descuento_usd", "neto_usd"],
        cop_cols_sixt=["tarifa_cop", "adicionales_cop", "descuento_cop", "neto_cop"],
    )


# =============================================================================
# KPIs principales (incluye RPD)
# =============================================================================
n_rentals = len(df_res)
tarifa = float(df_res[f"tarifa{suf}"].sum())
adic = float(df_res[f"adicionales{suf}"].sum())
neto = float(df_res[f"neto{suf}"].sum())
mix_pct = (adic / (tarifa + adic) * 100) if (tarifa + adic) else 0.0
rpd = ((tarifa + adic) / n_rentals) if n_rentals else 0.0

c1, c2, c3, c4, c5 = st.columns(5)
kpi(c1, "Rentals", fmt_int(n_rentals))
kpi(c2, "Tarifa (T)", fmt_money(tarifa, cur), fmt_money_short(tarifa, cur))
kpi(c3, "Adicionales", fmt_money(adic, cur), fmt_money_short(adic, cur))
kpi(c4, "RPD", fmt_money(rpd, cur), "(Tarifa + Adic) / Rentals")
kpi(c5, "% Adicionales", f"{mix_pct:.1f} %",
    f"Sobre tarifa+adic · Neto {fmt_money_short(neto, cur)}")

st.caption(
    "RPD = ingreso bruto por rental (Tarifa + Adicionales). "
    "Cuando seleccionas COP, los montos se recalculan con TRM Banrep oficial "
    "del dia de cada handover (no usamos la TRM interna de Sixt)."
)


# =============================================================================
# Mix tarifa vs adicionales por sede
# =============================================================================
section("Mix por sede")

if df_res.empty:
    st.info("Sin datos para los filtros seleccionados.")
else:
    df_sede = (
        df_res.groupby("sede_handover", as_index=False)
        .agg(
            tarifa=(f"tarifa{suf}", "sum"),
            adicionales=(f"adicionales{suf}", "sum"),
            rentals=("numero_contrato", "count"),
        )
        .sort_values("tarifa", ascending=False)
    )
    denom = (df_sede["tarifa"] + df_sede["adicionales"]).replace(0, pd.NA)
    df_sede["pct_adic"] = (df_sede["adicionales"] / denom * 100).fillna(0).round(1)
    df_sede["rpd"] = ((df_sede["tarifa"] + df_sede["adicionales"]) / df_sede["rentals"]).round(0)

    melted = df_sede.melt(
        id_vars=["sede_handover", "pct_adic", "rentals", "rpd"],
        value_vars=["tarifa", "adicionales"],
        var_name="componente", value_name="monto",
    )
    melted["componente"] = melted["componente"].map(
        {"tarifa": "Tarifa", "adicionales": "Adicionales"}
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
        view = df_sede[["sede_handover", "rentals", "tarifa",
                        "adicionales", "rpd", "pct_adic"]].copy()
        for col in ("tarifa", "adicionales", "rpd"):
            view[col] = view[col].apply(lambda v: fmt_money(v, cur))
        view["pct_adic"] = view["pct_adic"].apply(lambda v: f"{v:.1f} %")
        view = view.rename(columns={
            "sede_handover": "Sede",
            "rentals": "Rentals",
            "tarifa": f"Tarifa ({cur})",
            "adicionales": f"Adicionales ({cur})",
            "rpd": f"RPD ({cur})",
            "pct_adic": "% Adic",
        })
        st.dataframe(view, use_container_width=True, hide_index=True)


# =============================================================================
# Revenue por categoria de cargo (vw_rentals_detail)
# Tambien recalcula COP con Banrep TRM por linea.
# =============================================================================
section("Revenue por categoria de cargo")
st.caption(
    "Categorias del datashare: TARIFA (codigo T), CONTEXTO (location fee, "
    "airport fee...), COBERTURA (BF, SL, CDW), EXTRA (silla, GPS, AD), "
    "AJUSTE (descuentos no contractuales, redondeos), PENALIZACION "
    "(combustible faltante, abandono), OTROS."
)

# Pull per-line, aplicamos Banrep en pandas, y luego agregamos.
det_sql = """
SELECT d.cargo_categoria, d.cargo_codigo, d.cargo_descripcion,
       d.numero_contrato, d.fecha_handover_real,
       COALESCE(d.subtotal_usd, 0) AS subtotal_usd
FROM vw_rentals_detail d
WHERE d.fuente_cargo = 'RENTAL_COUNTER'
  AND d.rental_currency = 'USD'
  AND DATE(d.fecha_handover_real) BETWEEN ? AND ?
"""
det_params = [filtros.fecha_desde.isoformat(), filtros.fecha_hasta.isoformat()]
if filtros.sedes_codigos:
    ph = ",".join("?" * len(filtros.sedes_codigos))
    det_sql += f" AND d.sede_handover_codigo IN ({ph}) "
    det_params.extend(filtros.sedes_codigos)
if filtros.acriss:
    ph = ",".join("?" * len(filtros.acriss))
    det_sql += f" AND d.acriss_entregado IN ({ph}) "
    det_params.extend(filtros.acriss)

df_det = load_query(det_sql, tuple(det_params))
if not df_det.empty:
    df_det["subtotal_usd"] = pd.to_numeric(df_det["subtotal_usd"], errors="coerce").fillna(0.0)
    # Aplicar Banrep para crear subtotal_cop
    df_det = apply_trm(
        df_det, "Banrep", "fecha_handover_real",
        usd_cols=["subtotal_usd"], cop_cols_sixt=["subtotal_cop"],
    )
    money_col = f"subtotal{suf}"

    df_cat = (
        df_det.groupby("cargo_categoria", as_index=False)
        .agg(
            cargos=("cargo_codigo", "count"),
            contratos=("numero_contrato", "nunique"),
            monto=(money_col, "sum"),
        )
        .sort_values("monto", ascending=False)
    )

    c1, c2 = st.columns([2, 3])
    with c1:
        fig = px.pie(
            df_cat, names="cargo_categoria", values="monto",
            title=f"Distribucion ({cur})",
            color_discrete_sequence=[SIXT_ORANGE, SIXT_BLACK,
                                     "#666666", "#999999", "#cccccc",
                                     "#ffaa66", "#ffd1a8"],
        )
        fig.update_layout(**PLOTLY_LAYOUT)
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        view = df_cat.copy()
        view["monto"] = view["monto"].apply(lambda v: fmt_money(v, cur))
        view = view.rename(columns={
            "cargo_categoria": "Categoria",
            "cargos": "Cargos",
            "contratos": "Contratos",
            "monto": f"Revenue ({cur})",
        })
        st.dataframe(view, use_container_width=True, hide_index=True)

    # =========================================================================
    # Top 20 codigos de cargo
    # =========================================================================
    section("Top codigos de cargo (todos)")
    df_top = (
        df_det.groupby(
            ["cargo_categoria", "cargo_codigo", "cargo_descripcion"],
            as_index=False,
        )
        .agg(
            cargos=("cargo_codigo", "count"),
            contratos=("numero_contrato", "nunique"),
            monto=(money_col, "sum"),
        )
        .sort_values("monto", ascending=False)
        .head(20)
        .reset_index(drop=True)
    )
    if df_top["monto"].sum() > 0:
        df_top["pct_total"] = (df_top["monto"] / df_top["monto"].sum() * 100).round(1)
    else:
        df_top["pct_total"] = 0.0

    fig = px.bar(
        df_top, y="cargo_codigo", x="monto", color="cargo_categoria",
        orientation="h",
        title=f"Top 20 codigos por revenue ({cur})",
        hover_data=["cargo_descripcion", "cargos"],
        color_discrete_sequence=[SIXT_ORANGE, SIXT_BLACK,
                                 "#666666", "#999999", "#cccccc",
                                 "#ffaa66", "#ffd1a8"],
    )
    fig.update_layout(**PLOTLY_LAYOUT, xaxis_tickformat=",.0f",
                      yaxis=dict(autorange="reversed"))
    st.plotly_chart(fig, use_container_width=True)

    view = df_top.copy()
    view["monto"] = view["monto"].apply(lambda v: fmt_money(v, cur))
    view["pct_total"] = view["pct_total"].apply(lambda v: f"{v:.1f} %")
    view = view.rename(columns={
        "cargo_codigo": "Cod",
        "cargo_descripcion": "Descripcion",
        "cargo_categoria": "Categoria",
        "cargos": "Cargos",
        "contratos": "Contratos",
        "monto": f"Revenue ({cur})",
        "pct_total": "% del top 20",
    })
    st.dataframe(view, use_container_width=True, hide_index=True)
