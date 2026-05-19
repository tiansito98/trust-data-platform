"""
Vehiculos - Objetivo 5 del dashboard v2.

Distribucion por categoria ACRISS (codigo de 4 letras: M/E/C/I/S/F/P =
tamano, D/C/W/V/T = tipo carroceria, M/A = transmision, R/N/D = combustible).

Tres bloques:
  1. Distribucion por categoria ACRISS / label humano.
  2. Upgrades vs downgrades comparando acriss_reservado vs acriss_entregado.
  3. Top vehiculos fisicos (marca + modelo, por revenue).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import plotly.express as px
import streamlit as st

from components.common import (
    inject_styles, render_header, section, kpi, fmt_money, fmt_money_short,
    fmt_int, fmt_pct, load_query,
    PLOTLY_LAYOUT, SIXT_ORANGE, SIXT_BLACK,
)
from components.filters import render_sidebar_filters, render_active_filters_banner
from components.auth import require_auth, logout_button

st.set_page_config(page_title="TRUST - Vehiculos", layout="wide")
require_auth()
inject_styles()
logout_button()
render_header("Vehiculos: ACRISS, upgrades, top modelos")

filtros = render_sidebar_filters(default_days=90, show_acriss=True)
render_active_filters_banner(filtros)

where_sql, params = filtros.where_clause()
suf = "_usd" if filtros.moneda == "USD" else "_cop"
cur = filtros.moneda

# ---------- Distribucion por categoria entregada ----------
section("Distribucion por categoria entregada")
cat_sql = f"""
SELECT acriss_entregado, categoria_entregada,
       COUNT(*)                       AS rentals,
       SUM(neto_usd)                  AS neto_usd,
       AVG(neto_usd)                  AS ticket_usd,
       SUM(neto_cop)                  AS neto_cop,
       AVG(dias_renta * 1.0)          AS dias_avg,
       SUM(CASE WHEN acriss_reservado IS NOT NULL
                 AND acriss_entregado != acriss_reservado
                THEN 1 ELSE 0 END)    AS upgrades_o_downgrades,
       SUM(CASE WHEN acriss_reservado IS NULL THEN 1 ELSE 0 END) AS walk_in
FROM vw_rentals_resumen
WHERE {where_sql}
  AND acriss_entregado IS NOT NULL
GROUP BY acriss_entregado, categoria_entregada
ORDER BY rentals DESC
"""
df_cat = load_query(cat_sql, params)

if df_cat.empty:
    st.info("Sin contratos en los filtros seleccionados.")
    st.stop()

for c in ["rentals", "neto_usd", "ticket_usd", "neto_cop", "dias_avg",
          "upgrades_o_downgrades", "walk_in"]:
    df_cat[c] = pd.to_numeric(df_cat[c], errors="coerce").fillna(0.0)

total_rentals = int(df_cat["rentals"].sum())
total_neto = float(df_cat[f"neto{suf}"].sum())
total_ud = int(df_cat["upgrades_o_downgrades"].sum())
walk_in = int(df_cat["walk_in"].sum())

c1, c2, c3, c4 = st.columns(4)
kpi(c1, "Rentals", fmt_int(total_rentals))
kpi(c2, "Revenue neto", fmt_money(total_neto, cur), fmt_money_short(total_neto, cur))
kpi(c3, "Upgrades/Downgrades", fmt_int(total_ud),
    f"{(total_ud / max(1, total_rentals - walk_in)) * 100:.1f} % de los que tenian reserva")
kpi(c4, "Walk-ins", fmt_int(walk_in),
    f"{(walk_in / max(1, total_rentals)) * 100:.1f} % del total")

c_left, c_right = st.columns([3, 2])
with c_left:
    fig = px.bar(
        df_cat.head(15), x="acriss_entregado", y="rentals",
        color="categoria_entregada",
        title="Rentals por categoria ACRISS (top 15)",
        hover_data=["categoria_entregada", "neto_usd"],
    )
    fig.update_layout(**PLOTLY_LAYOUT, xaxis_title="",
                      legend=dict(orientation="h", y=-0.2))
    st.plotly_chart(fig, use_container_width=True)
with c_right:
    view = df_cat.head(15).copy()
    view[f"neto{suf}"] = view[f"neto{suf}"].apply(lambda v: fmt_money(v, cur))
    view["ticket_usd"] = view["ticket_usd"].apply(lambda v: fmt_money(v, "USD"))
    view["dias_avg"] = view["dias_avg"].round(1)
    view = view[["acriss_entregado", "categoria_entregada", "rentals",
                 f"neto{suf}", "ticket_usd", "dias_avg"]].rename(columns={
        "acriss_entregado": "ACRISS",
        "categoria_entregada": "Categoria",
        "rentals": "Rentals",
        f"neto{suf}": f"Neto ({cur})",
        "ticket_usd": "Ticket avg (USD)",
        "dias_avg": "Dias avg",
    })
    st.dataframe(view, use_container_width=True, hide_index=True)

# ---------- Upgrades vs downgrades ----------
section("Upgrades vs downgrades (reservado -> entregado)")
st.caption(
    "Comparamos acriss_reservado vs acriss_entregado en rentals que tenian "
    "reserva online. Si difiere, fue un cambio de categoria en counter."
)

ud_sql = f"""
SELECT acriss_reservado, acriss_entregado,
       COUNT(*) AS rentals,
       SUM(neto_usd) AS neto_usd,
       SUM(neto_cop) AS neto_cop
FROM vw_rentals_resumen
WHERE {where_sql}
  AND acriss_reservado IS NOT NULL
  AND acriss_entregado IS NOT NULL
  AND acriss_entregado != acriss_reservado
GROUP BY acriss_reservado, acriss_entregado
ORDER BY rentals DESC
"""
df_ud = load_query(ud_sql, params)
if not df_ud.empty:
    for c in ["rentals", "neto_usd", "neto_cop"]:
        df_ud[c] = pd.to_numeric(df_ud[c], errors="coerce").fillna(0.0)

if df_ud.empty:
    st.info("Sin cambios de categoria en el rango.")
else:
    df_ud["mov"] = df_ud["acriss_reservado"] + " -> " + df_ud["acriss_entregado"]
    fig = px.bar(
        df_ud.head(20), x="rentals", y="mov", orientation="h",
        title="Top 20 movimientos reservado -> entregado",
        color_discrete_sequence=[SIXT_ORANGE],
    )
    fig.update_layout(**PLOTLY_LAYOUT, yaxis=dict(autorange="reversed",
                                                   title=""))
    st.plotly_chart(fig, use_container_width=True)

    view = df_ud.copy()
    view[f"neto{suf}"] = view[f"neto{suf}"].apply(lambda v: fmt_money(v, cur))
    view = view[["acriss_reservado", "acriss_entregado", "rentals",
                 f"neto{suf}"]].rename(columns={
        "acriss_reservado": "Reservado",
        "acriss_entregado": "Entregado",
        "rentals": "Rentals",
        f"neto{suf}": f"Neto ({cur})",
    })
    st.dataframe(view, use_container_width=True, hide_index=True)

# ---------- Top modelos fisicos ----------
section("Top modelos fisicos entregados")
modelo_sql = f"""
SELECT vehiculo, COUNT(*) AS rentals,
       SUM(neto_usd) AS neto_usd,
       SUM(neto_cop) AS neto_cop,
       AVG(neto_usd) AS ticket_usd,
       SUM(dias_renta) AS dias_renta_tot,
       COUNT(DISTINCT placa) AS placas_distintas
FROM vw_rentals_resumen
WHERE {where_sql}
  AND vehiculo IS NOT NULL
GROUP BY vehiculo
ORDER BY rentals DESC
LIMIT 20
"""
df_mod = load_query(modelo_sql, params)
if not df_mod.empty:
    for c in ["rentals", "neto_usd", "neto_cop", "ticket_usd",
              "dias_renta_tot", "placas_distintas"]:
        df_mod[c] = pd.to_numeric(df_mod[c], errors="coerce").fillna(0.0)

if not df_mod.empty:
    fig = px.bar(
        df_mod, y="vehiculo", x="rentals", orientation="h",
        title="Top 20 modelos por numero de rentals",
        hover_data=["placas_distintas", "neto_usd"],
        color_discrete_sequence=[SIXT_ORANGE],
    )
    fig.update_layout(**PLOTLY_LAYOUT, yaxis=dict(autorange="reversed",
                                                   title=""))
    st.plotly_chart(fig, use_container_width=True)

    view = df_mod.copy()
    view[f"neto{suf}"] = view[f"neto{suf}"].apply(lambda v: fmt_money(v, cur))
    view["ticket_usd"] = view["ticket_usd"].apply(lambda v: fmt_money(v, "USD"))
    view = view[["vehiculo", "rentals", "placas_distintas",
                 "dias_renta_tot", f"neto{suf}", "ticket_usd"]].rename(columns={
        "vehiculo": "Vehiculo",
        "rentals": "Rentals",
        "placas_distintas": "Placas distintas",
        "dias_renta_tot": "Dias renta",
        f"neto{suf}": f"Neto ({cur})",
        "ticket_usd": "Ticket avg (USD)",
    })
    st.dataframe(view, use_container_width=True, hide_index=True)
