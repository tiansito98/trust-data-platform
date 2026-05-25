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

from components.auth import require_auth, require_page, logout_button
from components.common import (
    inject_styles, render_header, section, load_query, execute_write,
    fmt_money, render_trm_today_sidebar,
)

# --- Constantes de negocio ---
IVA_PORCENTAJE = 19.0  # IVA Colombia, hardcoded


st.set_page_config(page_title="TRUST - Facturas", layout="wide")
require_auth()
require_page("6_Facturas")
inject_styles()
# TRM Hoy en la sidebar (igual que en el resto de paginas). Esta pagina no
# llama render_sidebar_filters, asi que invocamos el bloque TRM directamente.
render_trm_today_sidebar()
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

    # --- Fila 3: monto en counter + monto prepagado (ambos CON IVA) ---
    c6, c7 = st.columns(2)
    monto_counter = c6.number_input(
        "Monto en counter (COP, con IVA)",
        min_value=0.0,
        step=1000.0,
        format="%.2f",
        help=("Lo que el counter cobra HOY al cliente, en pesos colombianos, "
              "con IVA incluido. Es el valor que aparece en el datafono cuando "
              "se pasa la tarjeta (o que se recibe en efectivo). Si todo fue "
              "pre-pagado y el cliente no paga nada aqui, deje en 0."),
    )
    monto_prepagado = c7.number_input(
        "Monto prepagado (COP, con IVA)",
        min_value=0.0,
        step=1000.0,
        format="%.2f",
        help=("Cuanto del total ya estaba pre-pagado por Sixt o por un tercero "
              "(CarTrawler, Booking, Hopper, etc.), en pesos colombianos y con "
              "IVA incluido. Si el cliente paga TODO aqui en el counter, "
              "deje en 0."),
    )

    # --- Auto-mostrar el TOTAL = counter + prepagado ---
    monto_total_preview = monto_counter + monto_prepagado
    if monto_total_preview > 0:
        st.markdown(
            f"<div style='background:#fff3e0;padding:8px 14px;"
            f"border-radius:4px;border-left:3px solid #ff6900;"
            f"margin:4px 0 12px 0;color:#333;font-size:0.95rem;'>"
            f"<strong>Monto total (con IVA):</strong> "
            f"{fmt_money(monto_total_preview, 'COP')} "
            f"&nbsp;<span style='color:#888;font-size:0.85rem;'>"
            f"(monto en counter + monto prepagado)</span>"
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
    # Calculo backend: monto_total se DERIVA de counter + prepagado.
    # IVA se extrae del total (hardcoded 19 %).
    monto_total = round(monto_counter + monto_prepagado, 2)
    iva_factor = 1 + IVA_PORCENTAJE / 100.0
    monto_base = round(monto_total / iva_factor, 2)
    iva = round(monto_total - monto_base, 2)
    prepaid = monto_prepagado > 0

    # Validaciones
    if monto_total <= 0:
        st.error("El monto total (counter + prepagado) debe ser mayor a 0.")
    elif not rntl_mvnr.strip().isdigit():
        st.error("El numero de contrato debe ser solo digitos.")
    else:

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
