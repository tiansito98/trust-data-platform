"""Capacidad y Flota: utilizacion mensual por sede x categoria + evolucion de flota."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
from components.common import (
    inject_styles, render_header, section,
    load_query, year_filter,
    SIXT_ORANGE, SIXT_BLACK, PLOTLY_LAYOUT,
    fmt_int, fmt_pct,
)

st.set_page_config(page_title="Capacidad y Flota - Trust v3", layout="wide")
inject_styles()
render_header("Capacidad y Flota")

lo_year, hi_year = year_filter("Rango de años a mostrar")

# ====================== CAPACIDAD - UTILIZACION ======================

section("Utilizacion mensual por sede y categoria ACRISS")

util = load_query(f"""
    SELECT
        anio_mes,
        sede_handover         AS sede,
        sede_handover_codigo  AS sede_codigo,
        acriss,
        rentals, dias_rentados,
        flota_acriss_mes, dias_disponibles_acriss_mes,
        utilizacion_pct
    FROM vw_utilizacion_sede_categoria_mes
    WHERE CAST(SUBSTR(anio_mes, 1, 4) AS INT) BETWEEN {lo_year} AND {hi_year}
      AND utilizacion_pct IS NOT NULL
    ORDER BY anio_mes, sede, acriss
""")

if util.empty:
    st.info("Sin datos en el rango seleccionado.")
else:
    sedes = ["(Todas)"] + sorted(util["sede"].dropna().unique().tolist())
    acriss_opts = ["(Todas)"] + sorted(util["acriss"].dropna().unique().tolist())
    c1, c2 = st.columns(2)
    sede_sel = c1.selectbox("Filtrar sede", sedes)
    acriss_sel = c2.selectbox("Filtrar ACRISS", acriss_opts)

    fdf = util.copy()
    if sede_sel != "(Todas)":
        fdf = fdf[fdf["sede"] == sede_sel]
    if acriss_sel != "(Todas)":
        fdf = fdf[fdf["acriss"] == acriss_sel]

    # Heatmap: filas = sede+acriss, columnas = anio_mes
    if not fdf.empty:
        if sede_sel == "(Todas)" and acriss_sel == "(Todas)":
            # Agregamos por (sede, acriss) para no saturar el heatmap
            piv = fdf.pivot_table(
                index="acriss", columns="anio_mes",
                values="utilizacion_pct", aggfunc="mean",
            )
            heat_title = "Utilizacion % por ACRISS (promedio entre sedes) x mes"
        elif sede_sel != "(Todas)" and acriss_sel == "(Todas)":
            piv = fdf.pivot_table(
                index="acriss", columns="anio_mes",
                values="utilizacion_pct", aggfunc="mean",
            )
            heat_title = f"Utilizacion % por ACRISS x mes - {sede_sel}"
        elif sede_sel == "(Todas)" and acriss_sel != "(Todas)":
            piv = fdf.pivot_table(
                index="sede", columns="anio_mes",
                values="utilizacion_pct", aggfunc="mean",
            )
            heat_title = f"Utilizacion % por sede x mes - {acriss_sel}"
        else:
            piv = fdf.pivot_table(
                index="sede", columns="anio_mes",
                values="utilizacion_pct", aggfunc="mean",
            )
            heat_title = f"Utilizacion % - {sede_sel} - {acriss_sel}"

        fig = px.imshow(
            piv,
            color_continuous_scale=[[0, "#ffffff"], [0.5, SIXT_ORANGE], [1, SIXT_BLACK]],
            aspect="auto",
            labels=dict(color="Util %"),
            title=heat_title,
        )
        fig.update_layout(**PLOTLY_LAYOUT, height=480)
        st.plotly_chart(fig, use_container_width=True)

    section("Tabla de utilizacion (top 30 por mes-sede-acriss del rango)")
    show = fdf.sort_values("anio_mes", ascending=False).head(30).copy()
    for c in ("rentals", "dias_rentados", "flota_acriss_mes", "dias_disponibles_acriss_mes"):
        show[c] = show[c].map(fmt_int)
    show["utilizacion_pct"] = show["utilizacion_pct"].map(fmt_pct)
    st.dataframe(
        show.rename(columns={
            "anio_mes": "Mes",
            "sede": "Sede",
            "acriss": "ACRISS",
            "rentals": "Rentals",
            "dias_rentados": "Dias rentados",
            "flota_acriss_mes": "Flota ACRISS",
            "dias_disponibles_acriss_mes": "Dias disp.",
            "utilizacion_pct": "Utilizacion %",
        }).drop(columns=["sede_codigo"]),
        hide_index=True, use_container_width=True,
    )

st.divider()

# ====================== FLOTA - EVOLUCION ANUAL ======================

section("Evolucion de la flota por segmento (ACRISS) y sede")

flota = load_query(f"""
    SELECT
        anio,
        sede,
        sede_codigo,
        acriss,
        vehiculos
    FROM vw_flota_segmento_anual
    WHERE anio BETWEEN {lo_year} AND {hi_year}
    ORDER BY anio, sede, acriss
""")

if flota.empty:
    st.info("Sin data de flota en el rango.")
else:
    # 1) Stacked bar por año: total flota dividida por ACRISS
    pivot_acriss = flota.groupby(["anio", "acriss"], as_index=False)["vehiculos"].sum()
    fig = px.bar(
        pivot_acriss, x="anio", y="vehiculos", color="acriss",
        title="Flota total por ACRISS (todas las sedes)",
    )
    fig.update_layout(
        **PLOTLY_LAYOUT,
        barmode="stack",
        yaxis=dict(title="Vehiculos"),
        xaxis=dict(title="Año", dtick=1),
        height=440,
        legend=dict(title="ACRISS"),
    )
    st.plotly_chart(fig, use_container_width=True)

    # 2) Stacked bar por año dividido por sede
    pivot_sede = flota.groupby(["anio", "sede"], as_index=False)["vehiculos"].sum()
    fig2 = px.bar(
        pivot_sede, x="anio", y="vehiculos", color="sede",
        title="Flota total por sede (todas las categorias)",
    )
    fig2.update_layout(
        **PLOTLY_LAYOUT,
        barmode="stack",
        yaxis=dict(title="Vehiculos"),
        xaxis=dict(title="Año", dtick=1),
        height=440,
        legend=dict(title="Sede"),
    )
    st.plotly_chart(fig2, use_container_width=True)

    section("Heatmap: vehiculos por ACRISS x año")
    hm = flota.groupby(["anio", "acriss"], as_index=False)["vehiculos"].sum()
    piv = hm.pivot(index="acriss", columns="anio", values="vehiculos").fillna(0)
    fig3 = px.imshow(
        piv,
        color_continuous_scale=[[0, "#ffffff"], [1, SIXT_ORANGE]],
        aspect="auto",
        labels=dict(color="Vehiculos"),
        text_auto=True,
    )
    fig3.update_layout(**PLOTLY_LAYOUT, height=420)
    st.plotly_chart(fig3, use_container_width=True)

    section("Detalle flota por año-sede-ACRISS")
    st.dataframe(
        flota.rename(columns={
            "anio": "Año",
            "sede": "Sede",
            "sede_codigo": "Sede codigo",
            "acriss": "ACRISS",
            "vehiculos": "Vehiculos",
        }),
        hide_index=True, use_container_width=True, height=400,
    )

with st.expander("Notas de calculo"):
    st.markdown(
        """
        - **Utilizacion mensual**: por (anio_mes, sede, ACRISS) se calculan los
          `dias_rentados` (suma de `dias_renta` con handover en ese mes/sede/categoria)
          y los `dias_disponibles` (dias-vehiculo de la categoria en ese mes,
          agnostico a sede).
        - **Limitacion**: el denominador de utilizacion (`dias_disponibles_acriss_mes`)
          es agnostico a sede porque Sixt no expone la sede home del vehiculo
          por mes. Por eso el ratio puede inflarse si una sede concentra la
          flota efectiva de un ACRISS.
        - **Flota por sede** = sede donde el vehiculo tuvo mas handovers en el
          año. Un mismo carro se cuenta una sola vez por año (en su sede
          dominante).
        """
    )
