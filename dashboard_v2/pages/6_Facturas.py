"""
Facturas - captura de recibos / facturas.

Tres secciones, top→bottom:
  1. Buscar contrato (referencia): el counter pega el numero, ve el detalle.
  2. Nueva factura: form que escribe a operational.invoices.
  3. Ultimas 25 facturas capturadas.

El campo "Numero contrato" del form se auto-rellena con lo que el usuario
escribio en el buscador, para evitar copy-paste extra.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import datetime as dt

import pandas as pd
import streamlit as st

from components.auth import require_auth, logout_button
from components.common import (
    inject_styles, render_header, section, load_query, execute_write,
    fmt_money, fmt_int, kpi,
)

st.set_page_config(page_title="TRUST - Facturas", layout="wide")
require_auth()
inject_styles()
logout_button()
render_header("Facturas / Recibos")

st.caption(
    "Captura de facturas / recibos. Escribe a `operational.invoices`. "
    "Usa el buscador de contrato para referenciar montos antes de digitar."
)

# Cargar sedes para el form (independiente del buscador).
sedes = load_query(
    "SELECT DISTINCT sede_handover_codigo AS codigo, sede_handover AS nombre "
    "FROM vw_rentals_resumen "
    "WHERE sede_handover IS NOT NULL "
    "ORDER BY sede_handover"
)
sede_map = dict(zip(sedes["nombre"], sedes["codigo"].astype(int)))


# =============================================================================
# 1. BUSCAR CONTRATO (referencia, no edita nada)
# =============================================================================
section("Buscar contrato (referencia)")
contrato_lookup = st.text_input(
    "Numero de contrato",
    placeholder="ej. 9523235185",
    key="lookup_contrato",
    help="Pega aqui el numero de contrato (rntl_mvnr). Veras debajo el detalle "
         "de cargos y totales. Despues llena el form con el numero de recibo y "
         "el total cobrado.",
)

contrato_int = None
contrato_str = contrato_lookup.strip()
if contrato_str.isdigit():
    contrato_int = int(contrato_str)

    # Header del contrato desde vw_rentals_resumen (1 fila).
    df_head = load_query(
        "SELECT numero_contrato, fecha_handover_real, fecha_devolucion_real, "
        "       dias_renta, sede_handover, placa, vehiculo, categoria_entregada, "
        "       acriss_entregado, forma_pago, reserva_prepagada, "
        "       tarifa_usd, adicionales_codigos, adicionales_usd, "
        "       descuento_usd, neto_usd, iva_usd, total_con_iva_usd, "
        "       tarifa_cop, adicionales_cop, descuento_cop, neto_cop, iva_cop, "
        "       total_con_iva_cop "
        "FROM vw_rentals_resumen WHERE numero_contrato = :n",
        {"n": contrato_int},
    )
    if df_head.empty:
        st.warning(f"No se encontro el contrato {contrato_int} en silver.")
    else:
        head = df_head.iloc[0]

        # KPIs cabecera del contrato
        c1, c2, c3, c4 = st.columns(4)
        kpi(c1, "Sede", head["sede_handover"] or "-")
        fecha_str = (
            pd.to_datetime(head["fecha_handover_real"]).strftime("%Y-%m-%d")
            if pd.notna(head["fecha_handover_real"]) else "-"
        )
        kpi(c2, "Entrega", fecha_str,
            f"{int(head['dias_renta']) if pd.notna(head['dias_renta']) else '-'} dias")
        veh = head["vehiculo"] or "-"
        plate = head["placa"] or "-"
        kpi(c3, "Vehiculo", f"{veh}",
            f"{plate} · {head['acriss_entregado'] or ''}")
        # Mostrar total en COP (es lo que el counter cobra) + USD entre parentesis
        try:
            total_cop = float(head["total_con_iva_cop"]) if pd.notna(head["total_con_iva_cop"]) else 0.0
        except Exception:
            total_cop = 0.0
        try:
            total_usd = float(head["total_con_iva_usd"]) if pd.notna(head["total_con_iva_usd"]) else 0.0
        except Exception:
            total_usd = 0.0
        kpi(c4, "TOTAL c/IVA (COP)", fmt_money(total_cop, "COP"),
            f"USD {fmt_money(total_usd, 'USD')}")

        # Detalle: cargos del counter, fila por cargo.
        df_items = load_query(
            "SELECT cargo_inty, cargo_codigo, cargo_descripcion, cargo_categoria, "
            "       cantidad, subtotal_con_iva_usd, subtotal_con_iva_cop "
            "FROM vw_rentals_detail "
            "WHERE numero_contrato = :n AND fuente_cargo = 'RENTAL_COUNTER' "
            "ORDER BY cargo_inty, cargo_posicion",
            {"n": contrato_int},
        )

        if df_items.empty:
            st.info("Contrato encontrado pero sin cargos del counter.")
        else:
            # Coercion preventiva
            for col in ("subtotal_con_iva_usd", "subtotal_con_iva_cop"):
                df_items[col] = pd.to_numeric(df_items[col], errors="coerce").fillna(0.0)
            df_items["cantidad"] = (
                pd.to_numeric(df_items["cantidad"], errors="coerce")
                .fillna(0).astype("Int64").astype(str)
            )

            # Linea por cargo
            det_view = df_items[[
                "cargo_inty", "cargo_codigo", "cargo_descripcion",
                "cargo_categoria", "cantidad",
                "subtotal_con_iva_cop", "subtotal_con_iva_usd",
            ]].copy()
            det_view["subtotal_con_iva_cop"] = det_view["subtotal_con_iva_cop"].apply(
                lambda v: fmt_money(v, "COP"))
            det_view["subtotal_con_iva_usd"] = det_view["subtotal_con_iva_usd"].apply(
                lambda v: fmt_money(v, "USD"))
            det_view = det_view.rename(columns={
                "cargo_inty": "Tipo",
                "cargo_codigo": "Cod",
                "cargo_descripcion": "Descripcion",
                "cargo_categoria": "Categoria",
                "cantidad": "Cant",
                "subtotal_con_iva_cop": "Subtotal c/IVA (COP)",
                "subtotal_con_iva_usd": "Subtotal c/IVA (USD)",
            })

            # Footer estilo factura: bruto, descuento, TOTAL CON IVA.
            # Los items en df_items ya vienen con IVA, asi que multiplicamos
            # bruto/descuento del head por 1.19 para que las sumas cuadren.
            iva_factor = 1.19
            try:
                bruto_iva_cop = float(head["bruto_cop"]) * iva_factor if pd.notna(head["bruto_cop"]) else 0.0
                bruto_iva_usd = float(head["bruto_usd"]) * iva_factor if pd.notna(head["bruto_usd"]) else 0.0
                desc_iva_cop = float(head["descuento_cop"]) * iva_factor if pd.notna(head["descuento_cop"]) else 0.0
                desc_iva_usd = float(head["descuento_usd"]) * iva_factor if pd.notna(head["descuento_usd"]) else 0.0
            except Exception:
                bruto_iva_cop = bruto_iva_usd = desc_iva_cop = desc_iva_usd = 0.0

            footer = pd.DataFrame([
                {"Tipo": "", "Cod": "", "Descripcion": "--- Subtotal bruto ---",
                 "Categoria": "", "Cant": "",
                 "Subtotal c/IVA (COP)": fmt_money(bruto_iva_cop, "COP"),
                 "Subtotal c/IVA (USD)": fmt_money(bruto_iva_usd, "USD")},
                {"Tipo": "", "Cod": "", "Descripcion": "--- Descuento ---",
                 "Categoria": "", "Cant": "",
                 "Subtotal c/IVA (COP)": fmt_money(-desc_iva_cop, "COP"),
                 "Subtotal c/IVA (USD)": fmt_money(-desc_iva_usd, "USD")},
                {"Tipo": "", "Cod": "", "Descripcion": "*** TOTAL CON IVA ***",
                 "Categoria": "", "Cant": "",
                 "Subtotal c/IVA (COP)": fmt_money(total_cop, "COP"),
                 "Subtotal c/IVA (USD)": fmt_money(total_usd, "USD")},
            ])

            factura = pd.concat([det_view, footer], ignore_index=True)
            st.dataframe(factura, use_container_width=True, hide_index=True)
elif contrato_str:
    st.warning("El numero de contrato debe ser solo digitos.")


st.markdown("---")


# =============================================================================
# 2. NUEVA FACTURA (form)
# =============================================================================
section("Nueva factura")

# Pre-fill el numero de contrato con lo del buscador si esta valido.
default_rntl = str(contrato_int) if contrato_int is not None else ""

with st.form("invoice_form", clear_on_submit=True):
    c1, c2, c3 = st.columns(3)
    fecha_emision = c1.date_input("Fecha emision", value=dt.date.today())
    sede_nombre = c2.selectbox("Sede", options=list(sede_map.keys()))
    moneda = c3.selectbox("Moneda", options=["COP", "USD"], index=0)

    c4, c5, c6 = st.columns(3)
    rntl_mvnr = c4.text_input(
        "Numero contrato (rntl_mvnr)",
        value=default_rntl,
        placeholder="opcional",
        help="Auto-rellenado desde el buscador de arriba. Editable.",
    )
    numero_doc = c5.text_input("Numero documento / recibo",
                                placeholder="ej. FAC-12345")
    rsrv_resn = c6.text_input("Numero reserva (opcional)",
                               placeholder="opcional")

    c7, c8, c9 = st.columns(3)
    monto_base = c7.number_input("Monto base", min_value=0.0, step=1000.0,
                                  format="%.2f")
    iva = c8.number_input("IVA", min_value=0.0, step=1000.0, format="%.2f")
    monto_total = c9.number_input("Monto total", min_value=0.0, step=1000.0,
                                   format="%.2f")

    forma_pago = st.selectbox(
        "Forma de pago",
        options=["EFECTIVO", "TARJETA_CREDITO", "TARJETA_DEBITO",
                 "TRANSFERENCIA", "PSE", "OTRO"],
    )
    observaciones = st.text_area("Observaciones", height=80,
                                  placeholder="opcional")
    submitted = st.form_submit_button("Guardar factura")

if submitted:
    if monto_total <= 0:
        st.error("Monto total debe ser mayor a 0.")
    else:
        params = {
            "rntl_mvnr": int(rntl_mvnr) if rntl_mvnr.strip().isdigit() else None,
            "rsrv_resn": int(rsrv_resn) if rsrv_resn.strip().isdigit() else None,
            "sede_codigo": int(sede_map[sede_nombre]),
            "sede_nombre": sede_nombre,
            "fecha_emision": fecha_emision,
            "forma_pago": forma_pago,
            "moneda": moneda,
            "monto_base": monto_base or None,
            "iva": iva or None,
            "monto_total": monto_total,
            "numero_documento": numero_doc or None,
            "observaciones": observaciones or None,
            "capturado_por": st.session_state.get("dashboard_user", "unknown"),
        }
        try:
            execute_write(
                """
                INSERT INTO operational.invoices
                  (rntl_mvnr, rsrv_resn, sede_codigo, sede_nombre,
                   fecha_emision, forma_pago, moneda,
                   monto_base, iva, monto_total,
                   numero_documento, observaciones, capturado_por)
                VALUES
                  (:rntl_mvnr, :rsrv_resn, :sede_codigo, :sede_nombre,
                   :fecha_emision, :forma_pago, :moneda,
                   :monto_base, :iva, :monto_total,
                   :numero_documento, :observaciones, :capturado_por)
                """,
                params,
            )
            st.success(f"Factura guardada para {sede_nombre}, "
                       f"{fmt_money(monto_total, moneda)}.")
            load_query.clear()
        except Exception as e:
            st.error(f"Error guardando: {e}")


st.markdown("---")


# =============================================================================
# 3. ULTIMAS FACTURAS CAPTURADAS
# =============================================================================
section("Ultimas facturas capturadas")
df = load_query(
    """
    SELECT invoice_id, fecha_emision, sede_nombre, numero_documento,
           forma_pago, moneda, monto_base, iva, monto_total,
           rntl_mvnr, rsrv_resn, capturado_por, capturado_at
    FROM operational.invoices
    ORDER BY invoice_id DESC
    LIMIT 25
    """
)
if df.empty:
    st.info("Aun no hay facturas capturadas.")
else:
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.caption(f"Mostrando ultimas {len(df)} facturas.")
