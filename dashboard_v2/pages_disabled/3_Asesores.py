"""
Asesores - Objetivo 3 del dashboard v2.

Revenue por operador_handover_codigo. El nombre del asesor NO esta en el
datashare; solo se muestra el codigo. Cuando Trust provea un CSV de
mapping codigo -> nombre se cargaria como dim_employees_seed en silver.

Fuente: vw_rentals_resumen, columnas tarifa_usd / adicionales_usd / neto_usd.
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
    fmt_int, load_query,
    PLOTLY_LAYOUT, SIXT_ORANGE, SIXT_BLACK,
)
from components.filters import render_sidebar_filters, render_active_filters_banner

st.set_page_config(page_title="Trust v2 - Asesores", layout="wide")
inject_styles()
render_header("Revenue por Asesor (Operador Handover)")

filtros = render_sidebar_filters(default_days=90)
render_active_filters_banner(filtros)

st.info(
    "El datashare expone el codigo numerico del asesor (`operador_handover_codigo`), "
    "no el nombre. Cuando Trust comparta un CSV de mapping, se cargara como "
    "dim_employees_seed en silver y aparecera la columna 'nombre' aqui."
)

where_sql, params = filtros.where_clause()
suf = "_usd" if filtros.moneda == "USD" else "_cop"
cur = filtros.moneda

# ---------- Agregado por asesor ----------
asesor_sql = f"""
SELECT operador_handover_codigo,
       COUNT(*)                              AS rentals,
       SUM(neto_usd)                         AS neto_usd,
       AVG(neto_usd)                         AS ticket_usd,
       SUM(tarifa_usd)                       AS tarifa_usd,
       SUM(adicionales_usd)                  AS adicionales_usd,
       SUM(descuento_usd)                    AS descuento_usd,
       SUM(neto_cop)                         AS neto_cop,
       SUM(tarifa_cop)                       AS tarifa_cop,
       SUM(adicionales_cop)                  AS adicionales_cop,
       SUM(dias_renta)                       AS dias_renta
FROM vw_rentals_resumen
WHERE {where_sql}
  AND operador_handover_codigo IS NOT NULL
GROUP BY operador_handover_codigo
ORDER BY neto_usd DESC
"""
df = load_query(asesor_sql, params)

if df.empty:
    st.info("Sin contratos en los filtros seleccionados.")
    st.stop()

for c in ["rentals", "neto_usd", "ticket_usd", "tarifa_usd", "adicionales_usd",
          "descuento_usd", "neto_cop", "tarifa_cop", "adicionales_cop",
          "dias_renta"]:
    df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)

df["asesor"] = df["operador_handover_codigo"].astype("Int64").astype(str)
denom = (df["tarifa_usd"] + df["adicionales_usd"]).replace(0, np.nan)
df["pct_adic"] = (df["adicionales_usd"] / denom * 100).fillna(0).round(1)
df["ticket_usd"] = df["ticket_usd"].round(2)

# ---------- KPIs cabecera ----------
n_asesores = len(df)
top1 = df.iloc[0]
neto_total = df["neto_usd"].sum()
share_top1 = top1["neto_usd"] / neto_total * 100 if neto_total else 0

c1, c2, c3, c4 = st.columns(4)
kpi(c1, "Asesores activos", fmt_int(n_asesores))
kpi(c2, "Top 1", top1["asesor"],
    f"{int(top1['rentals'])} rentals - {fmt_money(top1['neto_usd'], 'USD')}")
kpi(c3, "Share Top 1", f"{share_top1:.1f} %")
top10_share = df.head(10)["neto_usd"].sum() / neto_total * 100 if neto_total else 0
kpi(c4, "Share Top 10", f"{top10_share:.1f} %")

# ---------- Top 20 grafica ----------
section("Top 20 asesores por revenue")
top = df.head(20).copy()
fig = px.bar(
    top, y="asesor",
    x=[f"tarifa{suf}", f"adicionales{suf}"],
    orientation="h",
    title=f"Tarifa vs Adicionales por asesor ({cur})",
    color_discrete_map={f"tarifa{suf}": SIXT_ORANGE,
                        f"adicionales{suf}": SIXT_BLACK},
)
fig.update_layout(**PLOTLY_LAYOUT, xaxis_tickformat=",.0f",
                  yaxis=dict(autorange="reversed", title=""),
                  legend=dict(orientation="h", y=-0.15))
# Renombrar leyenda.
new_names = {f"tarifa{suf}": "Tarifa", f"adicionales{suf}": "Adicionales"}
fig.for_each_trace(lambda t: t.update(name=new_names.get(t.name, t.name)))
st.plotly_chart(fig, use_container_width=True)

# ---------- Tabla completa con paginacion natural de Streamlit ----------
section("Detalle por asesor")
view = df[[
    "asesor", "rentals", f"tarifa{suf}", f"adicionales{suf}",
    f"neto{suf}", "ticket_usd", "pct_adic", "dias_renta",
]].copy()
view[f"tarifa{suf}"] = view[f"tarifa{suf}"].apply(lambda v: fmt_money(v, cur))
view[f"adicionales{suf}"] = view[f"adicionales{suf}"].apply(lambda v: fmt_money(v, cur))
view[f"neto{suf}"] = view[f"neto{suf}"].apply(lambda v: fmt_money(v, cur))
view["ticket_usd"] = view["ticket_usd"].apply(lambda v: fmt_money(v, "USD"))
view["pct_adic"] = view["pct_adic"].apply(lambda v: f"{v:.1f} %")
view = view.rename(columns={
    "asesor": "Codigo asesor",
    "rentals": "Rentals",
    f"tarifa{suf}": f"Tarifa ({cur})",
    f"adicionales{suf}": f"Adicionales ({cur})",
    f"neto{suf}": f"Neto ({cur})",
    "ticket_usd": "Ticket avg (USD)",
    "pct_adic": "% Adic",
    "dias_renta": "Dias renta",
})
st.dataframe(view, use_container_width=True, hide_index=True)
