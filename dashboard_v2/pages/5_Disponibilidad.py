"""
Disponibilidad - Extra del v2.

Snapshot de la flota actual (no historico): cuantos vehiculos hay por sede,
cuantos estan on-rent, cuantos ready-to-rent, cuantos en otros estados
(taller, transito, etc.). Fuente: vw_vehicle_current_state (silver).

Esta pagina IGNORA los filtros de fecha porque es un snapshot del estado
actual, no una agregacion historica. Solo respeta el filtro de sede.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import datetime as dt

import pandas as pd
import plotly.express as px
import streamlit as st

from components.common import (
    inject_styles, render_header, section, kpi, fmt_int, fmt_pct, load_query,
    xlsx_download_button,
    PLOTLY_LAYOUT, SIXT_ORANGE, SIXT_BLACK,
)
from components.filters import render_sidebar_filters, render_active_filters_banner
from components.auth import require_auth, require_page, logout_button

st.set_page_config(page_title="TRUST - Disponibilidad", layout="wide")
require_auth()
require_page("5_Disponibilidad")
inject_styles()
logout_button()
render_header("Disponibilidad de Flota (snapshot actual)")

filtros = render_sidebar_filters(default_days=30)
render_active_filters_banner(filtros)

st.caption(
    "Snapshot del estado actual de la flota. Ignora el rango de fechas "
    "(no es historico). Solo respeta el filtro de sede."
)

# vw_vehicle_current_state usa brnc_code (no sede_handover_codigo, son el mismo nombre).
sede_where = ""
sede_params = ()
if filtros.sedes_codigos:
    placeholders = ",".join("?" * len(filtros.sedes_codigos))
    sede_where = f" AND brnc_code IN ({placeholders})"
    sede_params = tuple(filtros.sedes_codigos)

# ---------- KPI cabecera ----------
totales = load_query(
    f"""
    SELECT COUNT(*)                                 AS total,
           SUM(vhcl_on_rent_flg)                    AS on_rent,
           SUM(vhcl_ready_to_rent_flg)              AS ready,
           SUM(CASE WHEN vhcl_on_rent_flg=0
                     AND vhcl_ready_to_rent_flg=0
                    THEN 1 ELSE 0 END)              AS otros
    FROM vw_vehicle_current_state
    WHERE 1=1 {sede_where}
    """,
    sede_params,
).iloc[0]

total = int(totales["total"]) if totales["total"] else 0
on_rent = int(totales["on_rent"]) if totales["on_rent"] else 0
ready = int(totales["ready"]) if totales["ready"] else 0
otros = int(totales["otros"]) if totales["otros"] else 0

c1, c2, c3, c4 = st.columns(4)
kpi(c1, "Flota total", fmt_int(total))
kpi(c2, "On rent", fmt_int(on_rent),
    fmt_pct((on_rent / total * 100) if total else 0))
kpi(c3, "Ready to rent", fmt_int(ready),
    fmt_pct((ready / total * 100) if total else 0))
kpi(c4, "En otros estados", fmt_int(otros),
    "Taller, transito, mantenimiento, etc.")

# ---------- Por sede ----------
section("Por sede")
df_sede = load_query(
    f"""
    SELECT brnc_name,
           COUNT(*)                                 AS total,
           SUM(vhcl_on_rent_flg)                    AS on_rent,
           SUM(vhcl_ready_to_rent_flg)              AS ready,
           SUM(CASE WHEN vhcl_on_rent_flg=0
                     AND vhcl_ready_to_rent_flg=0
                    THEN 1 ELSE 0 END)              AS otros
    FROM vw_vehicle_current_state
    WHERE 1=1 {sede_where}
    GROUP BY brnc_name
    ORDER BY total DESC
    """,
    sede_params,
)

if df_sede.empty:
    st.info("Sin vehiculos en las sedes seleccionadas.")
    st.stop()

for c in ["total", "on_rent", "ready", "otros"]:
    df_sede[c] = pd.to_numeric(df_sede[c], errors="coerce").fillna(0.0)

df_sede["utilizacion_pct"] = (
    df_sede["on_rent"] / df_sede["total"].clip(lower=1) * 100
).round(1)

c_left, c_right = st.columns([3, 2])
with c_left:
    melted = df_sede.melt(
        id_vars=["brnc_name"], value_vars=["on_rent", "ready", "otros"],
        var_name="estado", value_name="vehiculos",
    )
    melted["estado"] = melted["estado"].map({
        "on_rent": "On rent",
        "ready": "Ready to rent",
        "otros": "Otros",
    })
    fig = px.bar(
        melted, x="brnc_name", y="vehiculos", color="estado", barmode="stack",
        title="Composicion de flota por sede",
        color_discrete_map={"On rent": SIXT_ORANGE,
                            "Ready to rent": SIXT_BLACK,
                            "Otros": "#999999"},
    )
    fig.update_layout(**PLOTLY_LAYOUT, xaxis_title="", yaxis_title="Vehiculos",
                      legend=dict(orientation="h", y=-0.15))
    st.plotly_chart(fig, use_container_width=True)

with c_right:
    view = df_sede.copy()
    view["utilizacion_pct"] = view["utilizacion_pct"].apply(lambda v: f"{v:.1f} %")
    view = view.rename(columns={
        "brnc_name": "Sede",
        "total": "Total",
        "on_rent": "On rent",
        "ready": "Ready",
        "otros": "Otros",
        "utilizacion_pct": "Utilizacion",
    })
    st.dataframe(view, use_container_width=True, hide_index=True)
    xlsx_download_button(
        df_sede,
        file_name=f"disponibilidad_sede_{dt.date.today()}",
        sheet_name="Por sede",
        key="xlsx_disp_sede",
    )

# ---------- Por categoria ----------
section("Por categoria de grupo (CRS)")
df_cat = load_query(
    f"""
    SELECT vhgr_category_level1 AS tipo,
           vhgr_category_level2 AS categoria,
           vhgr_crs              AS crs,
           COUNT(*)              AS total,
           SUM(vhcl_on_rent_flg) AS on_rent,
           SUM(vhcl_ready_to_rent_flg) AS ready
    FROM vw_vehicle_current_state
    WHERE 1=1 {sede_where}
    GROUP BY vhgr_category_level1, vhgr_category_level2, vhgr_crs
    ORDER BY total DESC
    """,
    sede_params,
)

if not df_cat.empty:
    for c in ["total", "on_rent", "ready"]:
        df_cat[c] = pd.to_numeric(df_cat[c], errors="coerce").fillna(0.0)
    c1, c2 = st.columns([2, 3])
    with c1:
        df_cat_agg = df_cat.groupby("categoria", as_index=False)["total"].sum()
        fig = px.pie(
            df_cat_agg, names="categoria", values="total",
            title="Mix por categoria",
            color_discrete_sequence=[SIXT_ORANGE, SIXT_BLACK, "#666", "#999", "#ccc", "#fdb"],
        )
        fig.update_layout(**PLOTLY_LAYOUT)
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        df_cat["util_pct"] = (
            df_cat["on_rent"] / df_cat["total"].clip(lower=1) * 100
        ).round(1)
        view = df_cat.copy()
        view["util_pct"] = view["util_pct"].apply(lambda v: f"{v:.1f} %")
        view = view.rename(columns={
            "tipo": "Tipo",
            "categoria": "Categoria",
            "crs": "CRS",
            "total": "Total",
            "on_rent": "On rent",
            "ready": "Ready",
            "util_pct": "Utilizacion",
        })
        st.dataframe(view, use_container_width=True, hide_index=True)
        xlsx_download_button(
            df_cat,
            file_name=f"disponibilidad_categoria_{dt.date.today()}",
            sheet_name="Por categoria",
            key="xlsx_disp_categoria",
        )

# ---------- Detalle vehiculo por vehiculo ----------
section("Detalle por vehiculo (snapshot)")
df_det = load_query(
    f"""
    SELECT brnc_name, vhgr_crs, vhgr_category_level2,
           vhcl_int_num,
           vhcl_on_rent_flg, vhcl_ready_to_rent_flg,
           vhcl_pickup_date, vhcl_return_date
    FROM vw_vehicle_current_state
    WHERE 1=1 {sede_where}
    ORDER BY brnc_name, vhgr_category_level2, vhgr_crs
    """,
    sede_params,
)
if not df_det.empty:
    df_det["estado"] = df_det.apply(
        lambda r: "On rent" if r["vhcl_on_rent_flg"] == 1
        else "Ready to rent" if r["vhcl_ready_to_rent_flg"] == 1
        else "Otro",
        axis=1,
    )
    view = df_det[["brnc_name", "vhgr_crs", "vhgr_category_level2",
                   "vhcl_int_num", "estado",
                   "vhcl_pickup_date", "vhcl_return_date"]].rename(columns={
        "brnc_name": "Sede",
        "vhgr_crs": "CRS",
        "vhgr_category_level2": "Categoria",
        "vhcl_int_num": "Vehiculo (int_num)",
        "estado": "Estado",
        "vhcl_pickup_date": "Ultimo pickup",
        "vhcl_return_date": "Ultimo return",
    })
    view["Vehiculo (int_num)"] = view["Vehiculo (int_num)"].astype("Int64").astype(str)
    st.dataframe(view, use_container_width=True, hide_index=True)
    xlsx_download_button(
        df_det,
        file_name=f"disponibilidad_detalle_{dt.date.today()}",
        sheet_name="Detalle vehiculos",
        key="xlsx_disp_detalle",
    )
