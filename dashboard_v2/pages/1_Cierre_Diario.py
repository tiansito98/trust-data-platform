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

import datetime as dt

import pandas as pd
import streamlit as st

from components.common import (
    inject_styles, render_header, section, kpi, fmt_money, fmt_money_short,
    fmt_int, load_query, apply_trm, xlsx_download_button,
)
from components.filters import render_sidebar_filters, render_active_filters_banner
from components.auth import require_auth, require_page, logout_button

st.set_page_config(page_title="TRUST - Cierre Diario", layout="wide")
require_auth()
require_page("1_Cierre_Diario")
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
       neto_cop, iva_cop, total_con_iva_cop,
       -- Split por bucket de pago (TERCERO vs COUNTER) + canal operativo.
       -- partner_nombre = nombre largo del partner B2B (ej. "CarTrawler Colombia"),
       -- mas legible que tercero_nombre (agnc_subsidiary_name de dim_agencies).
       tipo_agencia_main, tercero_nombre, partner_nombre, canal_cobro_tarifa,
       forma_pago_main, forma_pago_main_codigo,
       forma_pago_secondary, forma_pago_secondary_codigo,
       bruto_main_usd, bruto_secondary_usd,
       descuento_main_usd, descuento_secondary_usd,
       pagado_tercero_usd, pagado_counter_usd,
       bruto_main_cop, bruto_secondary_cop,
       descuento_main_cop, descuento_secondary_cop,
       pagado_tercero_cop, pagado_counter_cop,
       -- Per-charge split (regla unificada Wholesaler + Sixt Prepago directo):
       -- prepagado_usd = SUM(prepagado_cargo) - descuento_main; net del bucket.
       -- counter_usd   = SUM(counter_cargo)   - descuento_secondary; net del bucket.
       prepagado_usd, counter_usd, prepagado_cop, counter_cop
FROM vw_rentals_resumen
WHERE {where_sql}
ORDER BY DATE(fecha_handover_real) DESC, numero_contrato
"""
df_resumen = load_query(resumen_sql, params)

# SQLite via pandas devuelve algunas sumas REAL como object. Coercion preventiva.
_num_cols = ["dias_renta", "tarifa_usd", "adicionales_usd", "bruto_usd",
             "descuento_usd", "neto_usd", "iva_usd", "total_con_iva_usd",
             "tarifa_cop", "adicionales_cop", "bruto_cop", "descuento_cop",
             "neto_cop", "iva_cop", "total_con_iva_cop",
             "bruto_main_usd", "bruto_secondary_usd",
             "descuento_main_usd", "descuento_secondary_usd",
             "pagado_tercero_usd", "pagado_counter_usd",
             "bruto_main_cop", "bruto_secondary_cop",
             "descuento_main_cop", "descuento_secondary_cop",
             "pagado_tercero_cop", "pagado_counter_cop",
             "prepagado_usd", "counter_usd",
             "prepagado_cop", "counter_cop"]
for _c in _num_cols:
    if _c in df_resumen.columns:
        df_resumen[_c] = pd.to_numeric(df_resumen[_c], errors="coerce").fillna(0.0)

# Si COP+Banrep, recalcular columnas _cop a partir de _usd x TRM Banrep.
if filtros.moneda == "COP":
    df_resumen = apply_trm(
        df_resumen, filtros.trm_source, "fecha_handover_real",
        usd_cols=["tarifa_usd", "adicionales_usd", "bruto_usd",
                  "descuento_usd", "neto_usd", "iva_usd", "total_con_iva_usd",
                  "bruto_main_usd", "bruto_secondary_usd",
                  "descuento_main_usd", "descuento_secondary_usd",
                  "pagado_tercero_usd", "pagado_counter_usd",
                  "prepagado_usd", "counter_usd"],
        cop_cols_sixt=["tarifa_cop", "adicionales_cop", "bruto_cop",
                       "descuento_cop", "neto_cop", "iva_cop", "total_con_iva_cop",
                       "bruto_main_cop", "bruto_secondary_cop",
                       "descuento_main_cop", "descuento_secondary_cop",
                       "pagado_tercero_cop", "pagado_counter_cop",
                       "prepagado_cop", "counter_cop"],
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
            "forma_pago", "partner_nombre", "reserva_prepagada",
            "operador_handover_codigo",
        ]
        view = df_resumen[cols_view].copy()
        view["numero_contrato"] = view["numero_contrato"].astype("Int64").astype(str)
        view["fecha_handover_real"] = pd.to_datetime(view["fecha_handover_real"]).dt.strftime("%Y-%m-%d")
        view["fecha_devolucion_real"] = pd.to_datetime(view["fecha_devolucion_real"]).dt.strftime("%Y-%m-%d")
        view["dias_renta"] = view["dias_renta"].astype("Int64").astype(str)
        view["operador_handover_codigo"] = view["operador_handover_codigo"].astype("Int64").astype(str)
        # Tercero: nombre largo del partner B2B (ej. "CarTrawler Colombia").
        # NaN -> string vacio, no "nan".
        view["partner_nombre"] = view["partner_nombre"].fillna("").astype(str)

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
            "partner_nombre": "Tercero",
            "reserva_prepagada": "Prepago",
            "operador_handover_codigo": "Asesor",
        })
        st.dataframe(view, use_container_width=True, hide_index=True)
        xlsx_download_button(
            df_resumen[cols_view],
            file_name=f"cierre_diario_resumen_{dt.date.today()}",
            sheet_name="Resumen contratos",
            key="xlsx_cierre_resumen",
        )

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
           subtotal_usd, subtotal_cop,
           subtotal_con_iva_usd, subtotal_con_iva_cop,
           bucket_pago, forma_pago_cargo, forma_pago_cargo_codigo,
           -- Per-cargo split (NUEVO): cuanto venia prepagado vs counter.
           prepagado_cargo_usd, counter_cargo_usd,
           prepagado_cargo_cop, counter_cargo_cop
    FROM vw_rentals_detail
    WHERE fuente_cargo = 'RENTAL_COUNTER'
      AND rental_currency = 'USD'
      AND CAST(numero_contrato AS BIGINT) IN ({placeholders})
    ORDER BY DATE(fecha_handover_real) DESC, numero_contrato,
             cargo_inty, cargo_posicion
    """
    df_det = load_query(detalle_sql, tuple(int(c) for c in contratos))
    for _c in ("subtotal_usd", "subtotal_cop",
               "subtotal_con_iva_usd", "subtotal_con_iva_cop",
               "prepagado_cargo_usd", "counter_cargo_usd",
               "prepagado_cargo_cop", "counter_cargo_cop"):
        df_det[_c] = pd.to_numeric(df_det[_c], errors="coerce").fillna(0.0)

    # Si COP+Banrep: recalcular columnas COP por linea a partir del USD x TRM.
    if filtros.moneda == "COP":
        df_det = apply_trm(
            df_det, filtros.trm_source, "fecha_handover_real",
            usd_cols=["subtotal_usd", "subtotal_con_iva_usd",
                      "prepagado_cargo_usd", "counter_cargo_usd"],
            cop_cols_sixt=["subtotal_cop", "subtotal_con_iva_cop",
                           "prepagado_cargo_cop", "counter_cargo_cop"],
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

    # Sufijos COP/USD para las nuevas columnas por bucket.
    bruto_main_col = f"bruto_main{suf}"
    bruto_sec_col = f"bruto_secondary{suf}"
    desc_main_col = f"descuento_main{suf}"
    desc_sec_col = f"descuento_secondary{suf}"
    # Per-charge split (NUEVO, reemplaza pagado_tercero/counter para el header):
    prepagado_col = f"prepagado{suf}"     # net rental-level
    counter_col = f"counter{suf}"          # net rental-level
    sub_col = f"subtotal{suf}"             # sin IVA, por linea
    sub_iva_col = f"subtotal_con_iva{suf}" # con IVA, por linea
    prep_cargo_col = f"prepagado_cargo{suf}"  # por linea
    count_cargo_col = f"counter_cargo{suf}"   # por linea

    # Render una factura por contrato (expander).
    for contrato_str in contratos_filtrados:
        contrato_int = int(contrato_str)
        df_lineas = df_det[df_det["numero_contrato"] == contrato_int].copy()
        if df_lineas.empty:
            continue
        head = df_resumen[df_resumen["numero_contrato"] == contrato_int].iloc[0]

        # Totales por bucket. Estos vienen ya calculados de silver.
        # IMPORTANT: usamos la NUEVA logica per-charge (prepagado/counter),
        # no la vieja inty-based (pagado_tercero/counter), porque la vieja
        # se rompe para Sixt Prepago directo donde TODOS los cargos son inty='M'.
        iva_factor = 1.19
        bruto_main = float(head[bruto_main_col]) if pd.notna(head[bruto_main_col]) else 0.0
        bruto_sec = float(head[bruto_sec_col]) if pd.notna(head[bruto_sec_col]) else 0.0
        desc_main = float(head[desc_main_col]) if pd.notna(head[desc_main_col]) else 0.0
        desc_sec = float(head[desc_sec_col]) if pd.notna(head[desc_sec_col]) else 0.0
        prepagado_v = float(head[prepagado_col]) if pd.notna(head[prepagado_col]) else 0.0
        counter_v = float(head[counter_col]) if pd.notna(head[counter_col]) else 0.0
        iva_v = float(head[f"iva{suf}"]) if pd.notna(head[f"iva{suf}"]) else 0.0
        neto_v = float(head[f"neto{suf}"]) if pd.notna(head[f"neto{suf}"]) else 0.0
        total_v = float(head[f"total_con_iva{suf}"]) if pd.notna(head[f"total_con_iva{suf}"]) else 0.0

        # Pago al tercero (prepagado) / counter CON IVA (para mostrar en el header).
        pagado_t_iva = prepagado_v * iva_factor
        pagado_c_iva = counter_v * iva_factor

        canal = head.get("canal_cobro_tarifa")
        es_wholesaler = (canal == "WHOLESALER")
        es_sixt_prepago = (canal == "SIXT_PREPAGO")
        # Para el label del wholesaler preferimos partner_nombre (ej.
        # "CarTrawler Colombia", de dim_partners) sobre tercero_nombre
        # ("CARTRAWLER", de dim_agencies). Si partner_nombre esta vacio,
        # caemos a tercero_nombre.
        partner_nombre = head.get("partner_nombre")
        tercero_nombre = head.get("tercero_nombre")
        nombre_tercero = (partner_nombre if pd.notna(partner_nombre) and partner_nombre
                          else tercero_nombre)

        # Etiqueta operativa del canal. El nombre del tercero va en su propia
        # columna ("Tercero") para no concatenarlo con el canal.
        if es_wholesaler:
            canal_label = "Wholesaler"
        elif es_sixt_prepago:
            canal_label = "Sixt Prepago"
        else:
            canal_label = ""  # COUNTER => vacio (preferencia usuario).

        fecha_str = pd.to_datetime(head["fecha_handover_real"]).strftime("%Y-%m-%d")
        titulo = (
            f"{contrato_str} - {fecha_str} - {head['sede_handover']} - "
            f"{head['vehiculo']} ({head['acriss_entregado']}) - "
            f"Total {fmt_money(total_v, cur)}"
        )

        with st.expander(titulo, expanded=False):
            # --- Header del contrato como TABLA (no markdown). Streamlit
            # interpreta '$' como delimitador LaTeX math, asi que cualquier
            # render via st.markdown con valores como '$155,03' se rompe. La
            # tabla es ademas mas legible y consistente con el resto del UI.
            header_row = {
                "Contrato": contrato_str,
                "Vehiculo": str(head["vehiculo"]) if pd.notna(head["vehiculo"]) else "-",
                "Placa": str(head["placa"]) if pd.notna(head["placa"]) else "-",
                "Sede": str(head["sede_handover"]) if pd.notna(head["sede_handover"]) else "-",
                "Handover": fecha_str,
                "Dias": str(int(head["dias_renta"])) if pd.notna(head["dias_renta"]) else "-",
                "Asesor": str(int(head["operador_handover_codigo"])) if pd.notna(head["operador_handover_codigo"]) else "-",
            }
            # Canal de cobro de la tarifa: WHOLESALER / SIXT_PREPAGO / COUNTER.
            # Tercero = nombre largo del partner (ej. "CarTrawler Colombia"),
            # mismo dato que en el resumen. Vacio para walk-ins / COUNTER puro.
            # Para WHOLESALER y SIXT_PREPAGO mostramos pago al tercero (c/IVA)
            # y pago en counter (c/IVA). Para COUNTER puro, dejamos vacias esas
            # 3 celdas (preferencia del usuario: no mostrar '$0' placeholders).
            header_row["Canal"] = canal_label
            header_row["Tercero"] = (nombre_tercero
                                     if nombre_tercero and (es_wholesaler or es_sixt_prepago)
                                     else "")
            if es_wholesaler or es_sixt_prepago:
                header_row["Pago tercero (c/IVA)"] = fmt_money(pagado_t_iva, cur)
                header_row["Pago counter (c/IVA)"] = fmt_money(pagado_c_iva, cur)
            else:
                header_row["Pago tercero (c/IVA)"] = ""
                header_row["Pago counter (c/IVA)"] = ""
            header_row[f"Total c/IVA"] = fmt_money(total_v, cur)
            st.dataframe(pd.DataFrame([header_row]),
                         use_container_width=True, hide_index=True)

            # --- Lineas de detalle (sin IVA por linea — IVA se muestra una vez al
            # final). Columnas siguiendo el mockup: Origen | Inty | Bucket |
            # Forma de pago | Cod | Descripcion | Categoria | Cant | Subtotal.
            money_label = f"Subtotal ({cur})"

            # Bucket per-cargo: NUEVO. Etiqueta PREPAGO / COUNTER / MIXTO
            # derivada de prepagado_cargo_usd y counter_cargo_usd. Esto
            # reemplaza el bucket_pago viejo (inty-based) que daba labels
            # incorrectos para Sixt Prepago directo.
            def _bucket_label(row):
                prep = float(row.get(prep_cargo_col) or 0)
                cnt = float(row.get(count_cargo_col) or 0)
                if prep > 0 and cnt > 0:
                    return f"MIXTO ({fmt_money(prep, cur)} prepago, {fmt_money(cnt, cur)} counter)"
                if prep > 0:
                    return "PREPAGO"
                if cnt > 0:
                    return "COUNTER"
                return "-"
            df_lineas = df_lineas.copy()
            df_lineas["__bucket_display"] = df_lineas.apply(_bucket_label, axis=1)

            det_view = df_lineas[[
                "origen", "cargo_inty", "__bucket_display", "forma_pago_cargo",
                "forma_pago_cargo_codigo",
                "cargo_codigo", "cargo_descripcion", "cargo_categoria",
                "cantidad", sub_col,
            ]].copy()
            det_view[sub_col] = det_view[sub_col].apply(lambda v: fmt_money(v, cur))
            det_view["cantidad"] = det_view["cantidad"].astype("Int64").astype(str)

            # Forma de pago: "descripcion (CODIGO)" si ambos; fallback a uno solo.
            def _fmt_forma_pago(row):
                desc = row["forma_pago_cargo"]
                cod = row["forma_pago_cargo_codigo"]
                if pd.isna(desc) and pd.isna(cod):
                    return "-"
                if pd.notna(desc) and pd.notna(cod):
                    return f"{desc} ({cod})"
                return str(desc if pd.notna(desc) else cod)
            det_view["forma_pago_cargo"] = det_view.apply(_fmt_forma_pago, axis=1)
            det_view = det_view.drop(columns=["forma_pago_cargo_codigo"])

            det_view = det_view.rename(columns={
                "origen": "Origen",
                "cargo_inty": "Inty",
                "__bucket_display": "Bucket",
                "forma_pago_cargo": "Forma de pago",
                "cargo_codigo": "Cod",
                "cargo_descripcion": "Descripcion",
                "cargo_categoria": "Categoria",
                "cantidad": "Cant",
                sub_col: money_label,
            })

            # --- Footer: split per-charge (prepagado vs counter) + descuentos
            # + neto + IVA + total. Las sumas brutas de prepagado/counter se
            # calculan en pandas desde las columnas per-cargo para que el
            # subtotal sea independiente de los descuentos (que se muestran
            # como linea separada). Despues prepagado_v y counter_v ya son
            # netos (silver les resto descuento_main / descuento_secondary).
            bruto_prep = float(df_lineas[prep_cargo_col].sum())
            bruto_cnt = float(df_lineas[count_cargo_col].sum())

            empty = {"Origen": "", "Inty": "", "Bucket": "", "Forma de pago": "",
                     "Cod": "", "Descripcion": "", "Categoria": "", "Cant": "",
                     money_label: ""}
            footer_rows = []
            footer_rows.append({**empty,
                "Descripcion": "Subtotal prepagado",
                "Bucket": "PREPAGO",
                money_label: fmt_money(bruto_prep, cur)})
            footer_rows.append({**empty,
                "Descripcion": "Subtotal counter",
                "Bucket": "COUNTER",
                money_label: fmt_money(bruto_cnt, cur)})
            if desc_main > 0:
                footer_rows.append({**empty,
                    "Descripcion": "Descuento prepagado",
                    "Bucket": "PREPAGO",
                    money_label: fmt_money(-desc_main, cur)})
            if desc_sec > 0:
                footer_rows.append({**empty,
                    "Descripcion": "Descuento counter",
                    "Bucket": "COUNTER",
                    money_label: fmt_money(-desc_sec, cur)})
            footer_rows.append({**empty,
                "Descripcion": "--- Subtotal NETO ---",
                money_label: fmt_money(neto_v, cur)})
            footer_rows.append({**empty,
                "Descripcion": "IVA 19%",
                money_label: fmt_money(iva_v, cur)})
            footer_rows.append({**empty,
                "Descripcion": "*** TOTAL CON IVA ***",
                money_label: fmt_money(total_v, cur)})

            footer = pd.DataFrame(footer_rows)
            factura = pd.concat([det_view, footer], ignore_index=True)
            st.dataframe(factura, use_container_width=True, hide_index=True)
            xlsx_download_button(
                factura,
                file_name=f"factura_{contrato_str}_{dt.date.today()}",
                sheet_name=f"Contrato {contrato_str}",
                key=f"xlsx_factura_{contrato_str}",
            )
