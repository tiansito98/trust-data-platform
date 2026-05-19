"""
Cierre Diario - Objetivo 1 del dashboard v2.

Dos vistas en una sola pagina, con un toggle:

  (Q2) Resumen: 1 fila por contrato (default). Incluye fechas de entrega/
       devolucion, dias de renta y montos por componente.
  (Q1) Detalle: cada contrato muestra sus N cargos (subtotal CON IVA fila a
       fila desde silver) + 3 filas de totales (SUBTOTAL BRUTO c/IVA /
       DESCUENTO c/IVA / TOTAL CON IVA).

Las dos vienen directo de vw_rentals_resumen / vw_rentals_detail. Las filas
de totales se arman en Python a partir del resumen (no es SQL nuevo, solo
re-shape del mismo resumen). El dashboard nunca calcula totales.

Validacion: contrato 9523073821 (Rionegro, Abril 2026) = $826.95 USD.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import streamlit as st

from components.common import (
    inject_styles, render_header, section, kpi, fmt_money, fmt_money_short,
    fmt_int, load_query, apply_trm,
)
from components.filters import render_sidebar_filters, render_active_filters_banner
from components.auth import require_auth, logout_button

st.set_page_config(page_title="Trust v2 - Cierre Diario", layout="wide")
require_auth()
inject_styles()
logout_button()
render_header("Cierre Diario por Sede")

filtros = render_sidebar_filters(default_days=30)
render_active_filters_banner(filtros)

where_sql, params = filtros.where_clause()

# Toggle entre Q2 (default) y Q1.
modo = st.radio(
    "Vista",
    options=["Resumen (1 fila por contrato)", "Detalle por contrato (factura)"],
    horizontal=True,
    key="cierre_modo",
)

# Resumen siempre disponible: alimenta los KPIs.
resumen_sql = f"""
SELECT numero_contrato, fecha_handover_real, fecha_devolucion_real, dias_renta,
       sede_handover, placa, vehiculo, categoria_entregada,
       acriss_entregado, acriss_reservado, campaign, canal_partner,
       canal_principal, forma_pago, reserva_prepagada,
       operador_handover_codigo,
       tarifa_usd, adicionales_codigos, adicionales_usd,
       bruto_usd, descuento_usd, neto_usd, iva_usd, total_con_iva_usd,
       tarifa_cop, adicionales_cop, bruto_cop, descuento_cop,
       neto_cop, iva_cop, total_con_iva_cop
FROM vw_rentals_resumen
WHERE {where_sql}
ORDER BY DATE(fecha_handover_real) DESC, numero_contrato
"""
df_resumen = load_query(resumen_sql, params)

# SQLite via pandas devuelve algunas sumas REAL como object. Coercion preventiva.
_num_cols = ["dias_renta", "tarifa_usd", "adicionales_usd", "bruto_usd",
             "descuento_usd", "neto_usd", "iva_usd", "total_con_iva_usd",
             "tarifa_cop", "adicionales_cop", "bruto_cop", "descuento_cop",
             "neto_cop", "iva_cop", "total_con_iva_cop"]
for _c in _num_cols:
    if _c in df_resumen.columns:
        df_resumen[_c] = pd.to_numeric(df_resumen[_c], errors="coerce").fillna(0.0)

# Si COP+Banrep, recalcular columnas _cop a partir de _usd * TRM Banrep.
if filtros.moneda == "COP":
    df_resumen = apply_trm(
        df_resumen, filtros.trm_source, "fecha_handover_real",
        usd_cols=["tarifa_usd", "adicionales_usd", "bruto_usd",
                  "descuento_usd", "neto_usd", "iva_usd", "total_con_iva_usd"],
        cop_cols_sixt=["tarifa_cop", "adicionales_cop", "bruto_cop",
                       "descuento_cop", "neto_cop", "iva_cop", "total_con_iva_cop"],
    )

# ---------- KPIs cabecera ----------
if filtros.moneda == "USD":
    suf = "_usd"
    cur = "USD"
else:
    suf = "_cop"
    cur = "COP"

n_rentals = len(df_resumen)
neto = df_resumen[f"neto{suf}"].sum() if n_rentals else 0
iva = df_resumen[f"iva{suf}"].sum() if n_rentals else 0
total = df_resumen[f"total_con_iva{suf}"].sum() if n_rentals else 0
ticket = (neto / n_rentals) if n_rentals else 0

c1, c2, c3, c4 = st.columns(4)
kpi(c1, "Contratos", fmt_int(n_rentals))
kpi(c2, "Neto", fmt_money(neto, cur), fmt_money_short(neto, cur))
kpi(c3, "IVA 19%", fmt_money(iva, cur))
kpi(c4, "Total con IVA", fmt_money(total, cur), f"Ticket promedio {fmt_money(ticket, cur)}")

# ---------- Modo Resumen (Q2): tabla principal ----------
if modo.startswith("Resumen"):
    section("Resumen - 1 fila por contrato")
    if n_rentals == 0:
        st.info("Sin contratos para los filtros seleccionados.")
    else:
        cols_view = [
            "numero_contrato",
            "fecha_handover_real", "fecha_devolucion_real", "dias_renta",
            "sede_handover",
            "placa", "vehiculo", "categoria_entregada", "acriss_entregado",
            f"tarifa{suf}", "adicionales_codigos", f"adicionales{suf}",
            f"descuento{suf}", f"neto{suf}", f"iva{suf}", f"total_con_iva{suf}",
            "forma_pago", "reserva_prepagada", "operador_handover_codigo",
        ]
        view = df_resumen[cols_view].copy()
        view["numero_contrato"] = view["numero_contrato"].astype("Int64").astype(str)
        view["fecha_handover_real"] = pd.to_datetime(view["fecha_handover_real"]).dt.strftime("%Y-%m-%d")
        view["fecha_devolucion_real"] = pd.to_datetime(view["fecha_devolucion_real"]).dt.strftime("%Y-%m-%d")
        view["dias_renta"] = view["dias_renta"].astype("Int64").astype(str)
        view["operador_handover_codigo"] = view["operador_handover_codigo"].astype("Int64").astype(str)

        money_cols = [f"tarifa{suf}", f"adicionales{suf}", f"descuento{suf}",
                      f"neto{suf}", f"iva{suf}", f"total_con_iva{suf}"]
        for col in money_cols:
            view[col] = view[col].apply(lambda v: fmt_money(v, cur))

        view = view.rename(columns={
            "numero_contrato": "Contrato",
            "fecha_handover_real": "Entrega",
            "fecha_devolucion_real": "Devolucion",
            "dias_renta": "Dias",
            "sede_handover": "Sede",
            "placa": "Placa",
            "vehiculo": "Vehiculo",
            "categoria_entregada": "Categoria",
            "acriss_entregado": "ACRISS",
            f"tarifa{suf}": f"Tarifa ({cur})",
            "adicionales_codigos": "Adicionales (cods)",
            f"adicionales{suf}": f"Adic ({cur})",
            f"descuento{suf}": f"Descuento ({cur})",
            f"neto{suf}": f"Neto ({cur})",
            f"iva{suf}": f"IVA ({cur})",
            f"total_con_iva{suf}": f"Total c/IVA ({cur})",
            "forma_pago": "Forma pago",
            "reserva_prepagada": "Prepago",
            "operador_handover_codigo": "Asesor",
        })
        st.dataframe(view, use_container_width=True, hide_index=True)

# ---------- Modo Detalle (Q1): factura por contrato ----------
else:
    section("Detalle por contrato (estilo factura)")

    if n_rentals == 0:
        st.info("Sin contratos para los filtros seleccionados.")
        st.stop()

    # Lista de contratos (las del WHERE) para limitar la query de detalle.
    contratos = df_resumen["numero_contrato"].astype("Int64").astype(str).tolist()
    if not contratos:
        st.stop()

    placeholders = ",".join("?" * len(contratos))
    detalle_sql = f"""
    SELECT numero_contrato,
           fecha_handover_real, sede_handover, placa, vehiculo,
           categoria_entregada, acriss_entregado, acriss_reservado,
           operador_handover_codigo, forma_pago, prepago_flag AS reserva_prepagada,
           CASE WHEN cargo_coincide_reserva = 1 THEN 'RESERVA' ELSE 'COUNTER' END
               AS origen,
           cargo_inty, cargo_codigo, cargo_descripcion, cargo_categoria,
           cantidad,
           subtotal_con_iva_usd, subtotal_con_iva_cop
    FROM vw_rentals_detail
    WHERE fuente_cargo = 'RENTAL_COUNTER'
      AND rental_currency = 'USD'
      AND CAST(numero_contrato AS INTEGER) IN ({placeholders})
    ORDER BY DATE(fecha_handover_real) DESC, numero_contrato,
             cargo_inty, cargo_posicion
    """
    df_det = load_query(detalle_sql, tuple(int(c) for c in contratos))
    for _c in ("subtotal_con_iva_usd", "subtotal_con_iva_cop"):
        df_det[_c] = pd.to_numeric(df_det[_c], errors="coerce").fillna(0.0)

    # Si COP+Banrep: recalcular el subtotal_con_iva_cop a partir del USD x TRM.
    if filtros.moneda == "COP":
        df_det = apply_trm(
            df_det, filtros.trm_source, "fecha_handover_real",
            usd_cols=["subtotal_con_iva_usd"],
            cop_cols_sixt=["subtotal_con_iva_cop"],
        )

    money_col = f"subtotal_con_iva{suf}"

    # Buscador / limitador para no renderizar 500 facturas a la vez.
    n_max_default = 25
    cmax = st.number_input(
        "Maximo de contratos a renderizar",
        min_value=1, max_value=200, value=n_max_default, step=5,
        help="Para evitar render lento. Subi este numero si necesitas mas.",
    )
    buscar = st.text_input(
        "Filtrar por numero de contrato",
        value="",
        placeholder="ej. 9523073821",
    )
    if buscar.strip():
        contratos_filtrados = [c for c in contratos if buscar.strip() in c]
    else:
        contratos_filtrados = contratos
    contratos_filtrados = contratos_filtrados[: int(cmax)]

    st.caption(
        f"Mostrando {len(contratos_filtrados)} de {len(contratos)} contratos "
        f"que cumplen los filtros. Cada uno con {len(df_det)//max(1,len(contratos))}~ "
        f"cargos en promedio."
    )

    # Render una factura por contrato (expander).
    for contrato_str in contratos_filtrados:
        contrato_int = int(contrato_str)
        df_lineas = df_det[df_det["numero_contrato"] == contrato_int].copy()
        if df_lineas.empty:
            continue
        head = df_resumen[df_resumen["numero_contrato"] == contrato_int].iloc[0]

        # Los items en df_det ya vienen con IVA aplicado fila a fila desde silver,
        # asi que los totales del footer tambien se muestran con IVA para que el
        # cuadre sea: sum(items_con_iva) - descuento_con_iva = total_con_iva.
        iva_factor = 1.19
        bruto_con_iva = float(head[f"bruto{suf}"]) * iva_factor
        descuento_con_iva = float(head[f"descuento{suf}"]) * iva_factor
        total_v = float(head[f"total_con_iva{suf}"])

        fecha_str = pd.to_datetime(head["fecha_handover_real"]).strftime("%Y-%m-%d")
        titulo = (
            f"{contrato_str} - {fecha_str} - {head['sede_handover']} - "
            f"{head['vehiculo']} ({head['acriss_entregado']}) - "
            f"Total {fmt_money(total_v, cur)}"
        )

        with st.expander(titulo, expanded=(contrato_str == "9523073821")):
            meta = (
                f"**Placa:** {head['placa']} &nbsp;|&nbsp; "
                f"**Dias:** {int(head['dias_renta']) if pd.notna(head['dias_renta']) else '-'} &nbsp;|&nbsp; "
                f"**Asesor:** {int(head['operador_handover_codigo']) if pd.notna(head['operador_handover_codigo']) else '-'} &nbsp;|&nbsp; "
                f"**Forma pago:** {head['forma_pago']} &nbsp;|&nbsp; "
                f"**Prepago:** {head['reserva_prepagada']}"
            )
            st.markdown(meta)

            # Detalle de cargos.
            det_view = df_lineas[[
                "origen", "cargo_codigo", "cargo_descripcion",
                "cargo_categoria", "cantidad", money_col,
            ]].copy()
            det_view[money_col] = det_view[money_col].apply(lambda v: fmt_money(v, cur))
            # Coercion a string para concat con footer (que tiene "" en numericos).
            det_view["cantidad"] = det_view["cantidad"].astype("Int64").astype(str)
            money_label = f"Subtotal c/IVA ({cur})"
            det_view = det_view.rename(columns={
                "origen": "Origen",
                "cargo_codigo": "Cod",
                "cargo_descripcion": "Descripcion",
                "cargo_categoria": "Categoria",
                "cantidad": "Cant",
                money_col: money_label,
            })

            # Footer: 3 filas de totales (bruto, descuento, total). Como cada item
            # ya viene con IVA, no se muestra una linea separada de "IVA 19%".
            footer = pd.DataFrame([
                {"Origen": "", "Cod": "", "Descripcion": "--- Subtotal bruto ---",
                 "Categoria": "", "Cant": "",
                 money_label: fmt_money(bruto_con_iva, cur)},
                {"Origen": "", "Cod": "", "Descripcion": "--- Descuento ---",
                 "Categoria": "", "Cant": "",
                 money_label: fmt_money(-descuento_con_iva, cur)},
                {"Origen": "", "Cod": "", "Descripcion": "*** TOTAL CON IVA ***",
                 "Categoria": "", "Cant": "",
                 money_label: fmt_money(total_v, cur)},
            ])
            factura = pd.concat([det_view, footer], ignore_index=True)
            st.dataframe(factura, use_container_width=True, hide_index=True)

# ---------- Footer de validacion ----------
st.markdown("---")
st.caption(
    "Validacion: contrato 9523073821 (MEDELLIN AP JOSE MARIA CORDOVA, "
    "2026-04-28) debe sumar $826.95 USD total con IVA. "
    "Buscalo arriba para verificar visualmente."
)
