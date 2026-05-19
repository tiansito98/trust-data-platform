"""
Facturas - captura de recibos / facturas.

Form que escribe a operational.invoices en Supabase Postgres. La tabla la crea
scripts/setup_postgres.sql.

Lista las ultimas 25 facturas capturadas debajo del form.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import datetime as dt

import streamlit as st

from components.auth import require_auth, logout_button
from components.common import (
    inject_styles, render_header, section, load_query, execute_write,
    fmt_money, fmt_int,
)

st.set_page_config(page_title="Trust v2 - Facturas", layout="wide")
require_auth()
inject_styles()
render_header("Facturas / Recibos")
logout_button()

st.caption(
    "Captura de facturas / recibos. Escribe a `operational.invoices`. "
    "Para reportes agregados, ver paginas 1-2."
)

# ---------- Cargar opciones de sedes ----------
sedes = load_query(
    "SELECT DISTINCT sede_handover_codigo AS codigo, sede_handover AS nombre "
    "FROM vw_rentals_resumen "
    "WHERE sede_handover IS NOT NULL "
    "ORDER BY sede_handover"
)
sede_map = dict(zip(sedes["nombre"], sedes["codigo"].astype(int)))

# ---------- Form ----------
section("Nueva factura")
with st.form("invoice_form", clear_on_submit=True):
    c1, c2, c3 = st.columns(3)
    fecha_emision = c1.date_input("Fecha emision", value=dt.date.today())
    sede_nombre = c2.selectbox("Sede", options=list(sede_map.keys()))
    moneda = c3.selectbox("Moneda", options=["COP", "USD"], index=0)

    c4, c5, c6 = st.columns(3)
    numero_doc = c4.text_input("Numero documento", placeholder="ej. FAC-12345")
    rntl_mvnr = c5.text_input("Numero contrato (rntl_mvnr)", placeholder="opcional")
    rsrv_resn = c6.text_input("Numero reserva (opcional)", placeholder="opcional")

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
    observaciones = st.text_area("Observaciones", height=80, placeholder="opcional")
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
            # Refrescar el listing debajo
            load_query.clear()
        except Exception as e:
            st.error(f"Error guardando: {e}")

# ---------- Ultimas 25 facturas ----------
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
