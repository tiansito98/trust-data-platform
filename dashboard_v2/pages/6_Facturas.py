"""
Facturas - captura de facturas / recibos al cierre de cada contrato.

Form simple para que el asesor del counter registre:
  - Numero de contrato + factura + recibo
  - Monto total cobrado al cliente (IVA incluido — el sistema separa el 19 %)
  - Cuanto del total venia pre-pagado (por Sixt o un tercero como CarTrawler)
  - Lo que queda pagado en counter se calcula solo

Si el monto pre-pagado es > 0, la factura queda marcada como prepaid=True.
Si no, prepaid=False.

Escribe a operational.invoices.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import datetime as dt

import streamlit as st

from components.auth import require_auth, logout_button
from components.common import (
    inject_styles, render_header, section, load_query, execute_write,
    fmt_money,
)

# --- Constantes de negocio ---
IVA_PORCENTAJE = 19.0  # IVA Colombia, hardcoded


st.set_page_config(page_title="TRUST - Facturas", layout="wide")
require_auth()
inject_styles()
logout_button()
render_header("Facturas / Recibos")

st.caption(
    "Captura de facturas y recibos al cierre del contrato. "
    "El sistema calcula automaticamente el IVA (19 %) a partir del monto total."
)


# =============================================================================
# Cargar opciones de sedes
# =============================================================================
sedes = load_query(
    "SELECT DISTINCT sede_handover_codigo AS codigo, sede_handover AS nombre "
    "FROM vw_rentals_resumen "
    "WHERE sede_handover IS NOT NULL "
    "ORDER BY sede_handover"
)
sede_map = dict(zip(sedes["nombre"], sedes["codigo"].astype(int)))


# =============================================================================
# Form: Nueva factura
# =============================================================================
section("Nueva factura")

with st.form("invoice_form", clear_on_submit=True):
    # --- Fila 1: identificacion del contrato / fecha / sede ---
    c1, c2, c3 = st.columns(3)
    fecha_emision = c1.date_input(
        "Fecha emision",
        value=dt.date.today(),
        help="Fecha en que se emite la factura (normalmente hoy).",
    )
    sede_nombre = c2.selectbox(
        "Sede",
        options=list(sede_map.keys()),
        help="Sede donde se entrego el vehiculo.",
    )
    rntl_mvnr = c3.text_input(
        "Numero de contrato",
        placeholder="ej. 9523011485",
        help=("Numero del contrato de renta tal como aparece en el contrato "
              "firmado por el cliente."),
    )

    # --- Fila 2: numero de factura y numero de recibo ---
    c4, c5 = st.columns(2)
    numero_factura = c4.text_input(
        "Numero de factura",
        placeholder="ej. FAC-12345",
        help="Numero consecutivo de la factura DIAN.",
    )
    numero_recibo = c5.text_input(
        "Numero de recibo",
        placeholder="ej. 00045678",
        help="Numero del recibo del datafono o del comprobante de pago.",
    )

    # --- Fila 3: monto total + monto prepagado ---
    c6, c7 = st.columns(2)
    monto_total = c6.number_input(
        "Monto total (COP)",
        min_value=0.0,
        step=1000.0,
        format="%.2f",
        help=("Valor total cobrado al cliente, con IVA incluido. El sistema "
              "calcula automaticamente el 19 % de IVA y el monto base sin IVA."),
    )
    monto_prepagado = c7.number_input(
        "Monto prepagado (COP)",
        min_value=0.0,
        step=1000.0,
        format="%.2f",
        help=("Cuanto del total ya estaba pre-pagado por Sixt o por un tercero "
              "(CarTrawler, Booking, Hopper, etc.). "
              "Si el cliente paga TODO aqui en el counter, deje en 0."),
    )

    # --- Auto-mostrar lo que se paga en counter ---
    monto_counter_preview = max(monto_total - monto_prepagado, 0.0)
    if monto_total > 0:
        st.markdown(
            f"<div style='background:#fff3e0;padding:8px 14px;"
            f"border-radius:4px;border-left:3px solid #ff6900;"
            f"margin:4px 0 12px 0;color:#333;font-size:0.95rem;'>"
            f"<strong>Monto pagado en counter:</strong> "
            f"{fmt_money(monto_counter_preview, 'COP')} "
            f"&nbsp;<span style='color:#888;font-size:0.85rem;'>"
            f"(monto total &minus; monto prepagado)</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

    # --- Observaciones opcionales ---
    observaciones = st.text_area(
        "Observaciones",
        height=80,
        placeholder="Notas adicionales (opcional)",
        help="Notas adicionales (opcional).",
    )

    submitted = st.form_submit_button("Guardar factura")


# =============================================================================
# Procesar submit
# =============================================================================
if submitted:
    # Validaciones
    if monto_total <= 0:
        st.error("El monto total debe ser mayor a 0.")
    elif monto_prepagado > monto_total:
        st.error("El monto prepagado no puede ser mayor al monto total.")
    elif not rntl_mvnr.strip().isdigit():
        st.error("El numero de contrato debe ser solo digitos.")
    else:
        # Calculo backend: el sistema separa el IVA del monto total.
        iva_factor = 1 + IVA_PORCENTAJE / 100.0
        monto_base = round(monto_total / iva_factor, 2)
        iva = round(monto_total - monto_base, 2)
        monto_counter = round(monto_total - monto_prepagado, 2)
        prepaid = monto_prepagado > 0

        params = {
            "rntl_mvnr": int(rntl_mvnr.strip()),
            "sede_codigo": int(sede_map[sede_nombre]),
            "sede_nombre": sede_nombre,
            "fecha_emision": fecha_emision,
            "moneda": "COP",
            "numero_factura": numero_factura.strip() or None,
            "numero_recibo": numero_recibo.strip() or None,
            "monto_base": monto_base,
            "iva": iva,
            "monto_total": monto_total,
            "monto_prepagado": monto_prepagado,
            "monto_counter": monto_counter,
            "prepaid": prepaid,
            "observaciones": observaciones.strip() or None,
            "capturado_por": st.session_state.get("dashboard_user", "unknown"),
        }
        try:
            execute_write(
                """
                INSERT INTO operational.invoices
                  (rntl_mvnr, sede_codigo, sede_nombre, fecha_emision, moneda,
                   numero_factura, numero_recibo,
                   monto_base, iva, monto_total,
                   monto_prepagado, monto_counter, prepaid,
                   observaciones, capturado_por)
                VALUES
                  (:rntl_mvnr, :sede_codigo, :sede_nombre, :fecha_emision, :moneda,
                   :numero_factura, :numero_recibo,
                   :monto_base, :iva, :monto_total,
                   :monto_prepagado, :monto_counter, :prepaid,
                   :observaciones, :capturado_por)
                """,
                params,
            )
            tag = "prepagada" if prepaid else "no prepagada"
            st.success(
                f"Factura guardada — {sede_nombre} — "
                f"contrato {rntl_mvnr} — {fmt_money(monto_total, 'COP')} ({tag})."
            )
            load_query.clear()
        except Exception as e:
            st.error(f"Error guardando: {e}")


# =============================================================================
# Ultimas 25 facturas capturadas
# =============================================================================
st.markdown("---")
section("Ultimas facturas capturadas")
df = load_query(
    """
    SELECT invoice_id, fecha_emision, sede_nombre, rntl_mvnr,
           numero_factura, numero_recibo,
           monto_total, monto_prepagado, monto_counter, prepaid,
           capturado_por, capturado_at
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
