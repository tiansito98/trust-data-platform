"""
Facturas - captura, edicion, finalizacion y validacion de facturas.

Workflow:
  1. Asesor crea factura (draft, finalizada=FALSE).
  2. Mientras el rental esta abierto, puede editar montos / recibos.
  3. Cuando el vehiculo se devuelve, marca "Finalizar".
  4. El sistema valida: monto_total factura vs total_con_iva_cop de silver
     (calculado via charges * TRM Banrep). Si hay diferencia > $500 COP,
     muestra alarma y permite "Reabrir" para corregir.

Per-sede: usuarios sede solo ven facturas de su sucursal.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import datetime as dt

import pandas as pd
import streamlit as st

from components.auth import (
    require_auth, require_page, logout_button,
    get_user_branches, is_admin, get_current_user,
)
from components.common import (
    inject_styles, render_header, section, load_query, execute_write,
    fmt_money, render_trm_today_sidebar,
)

IVA_PORCENTAJE = 19.0
VALIDATION_TOLERANCE_COP = 500  # diferencia maxima aceptable
FECHA_INICIO_RECORDATORIO = "2026-06-01"  # handover >= esta fecha sin factura = pendiente


st.set_page_config(page_title="TRUST - Facturas", layout="wide")
require_auth()
require_page("6_Facturas")
inject_styles()
render_trm_today_sidebar()
logout_button()
render_header("Facturas / Recibos")


# =============================================================================
# Sede filtering
# =============================================================================
user_branches = get_user_branches()
user_is_admin = is_admin()
current_user = get_current_user()
username = current_user["username"] if current_user else "unknown"

# Build sede WHERE clause for all queries
if user_is_admin or "*" in user_branches:
    sede_where = ""
    sede_params = {}
else:
    sede_where = "AND i.sede_nombre = :user_sede"
    sede_params = {"user_sede": user_branches[0]}

# Load sedes for the form dropdown
sedes = load_query(
    "SELECT DISTINCT sede_handover_codigo AS codigo, sede_handover AS nombre "
    "FROM vw_rentals_resumen WHERE sede_handover IS NOT NULL "
    "ORDER BY sede_handover"
)
sede_map = dict(zip(sedes["nombre"], sedes["codigo"].astype(int)))


# Placeholder para el recordatorio de facturas pendientes. Se declara aqui
# (queda arriba del formulario) pero se RENDERIZA al final del script (ver
# "Seccion 0") para que refleje cualquier factura creada en este mismo run,
# despues de que load_query.clear() haya invalidado la cache.
reminder_slot = st.container()


# =============================================================================
# Session state for edit mode
# =============================================================================
if "_editing_id" not in st.session_state:
    st.session_state["_editing_id"] = None
if "_editing_data" not in st.session_state:
    st.session_state["_editing_data"] = {}

editing = st.session_state["_editing_id"] is not None
editing_data = st.session_state["_editing_data"]


# =============================================================================
# 1. FORM: Nueva factura / Editar factura
# =============================================================================
if editing:
    section(f"Editar factura #{st.session_state['_editing_id']}")
    st.caption("Editando factura existente. Modifica los campos y haz clic en 'Guardar cambios'.")
    if st.button("Cancelar edicion"):
        st.session_state["_editing_id"] = None
        st.session_state["_editing_data"] = {}
        st.rerun()
else:
    section("Nueva factura")

with st.form("invoice_form", clear_on_submit=not editing):
    c1, c2, c3 = st.columns(3)
    fecha_emision = c1.date_input(
        "Fecha emision",
        value=(editing_data.get("fecha_emision") or dt.date.today()),
        help="Fecha en que se emite la factura (normalmente hoy).",
    )
    # Sede: locked for sede users
    if user_is_admin or "*" in user_branches:
        sede_options = list(sede_map.keys())
        default_idx = 0
        if editing and editing_data.get("sede_nombre") in sede_options:
            default_idx = sede_options.index(editing_data["sede_nombre"])
        sede_nombre = c2.selectbox("Sede", options=sede_options, index=default_idx,
                                    help="Sede donde se entrego el vehiculo.")
    else:
        locked_sede = user_branches[0] if user_branches else ""
        c2.text_input("Sede (fija)", value=locked_sede, disabled=True)
        sede_nombre = locked_sede

    # Prefill: al editar, el contrato de la factura; si no, un contrato que el
    # asesor eligio desde el recordatorio de pendientes (Seccion 0). Como el
    # widget no tiene key, cambiar `value` lo re-inicializa (asi funciona el
    # prefill de edicion), por eso el prefill del recordatorio tambien aplica.
    if editing and editing_data.get("rntl_mvnr"):
        _default_contrato = str(int(editing_data["rntl_mvnr"]))
    else:
        _default_contrato = str(st.session_state.get("_prefill_contrato", "") or "")
    rntl_mvnr = c3.text_input(
        "Numero de contrato",
        value=_default_contrato,
        placeholder="ej. 9523011485",
        help="Numero del contrato de renta tal como aparece en el contrato firmado.",
    )

    c4, c5 = st.columns(2)
    numero_factura = c4.text_input(
        "Numero de factura",
        value=editing_data.get("numero_factura", "") or "",
        placeholder="ej. FAC-12345",
        help="Numero consecutivo de la factura DIAN.",
    )
    numero_recibo = c5.text_input(
        "Numero de recibo",
        value=editing_data.get("numero_recibo", "") or "",
        placeholder="ej. 00045678",
        help="Numero del recibo del datafono o del comprobante de pago.",
    )

    c6, c7 = st.columns(2)
    monto_counter = c6.number_input(
        "Monto en counter (COP, con IVA)",
        min_value=0.0, step=1000.0, format="%.2f",
        value=float(editing_data.get("monto_counter", 0) or 0),
        help="Lo que el counter cobra HOY al cliente, en pesos colombianos, con IVA incluido.",
    )
    monto_prepagado = c7.number_input(
        "Monto prepagado (COP, con IVA)",
        min_value=0.0, step=1000.0, format="%.2f",
        value=float(editing_data.get("monto_prepagado", 0) or 0),
        help="Cuanto del total ya estaba pre-pagado por Sixt o un tercero. Deje 0 si el cliente paga todo en counter.",
    )

    monto_total_preview = monto_counter + monto_prepagado
    if monto_total_preview > 0:
        st.markdown(
            f"<div style='background:#fff3e0;padding:8px 14px;border-radius:4px;"
            f"border-left:3px solid #ff6900;margin:4px 0 12px 0;color:#333;"
            f"font-size:0.95rem;'>"
            f"<strong>Monto total (con IVA):</strong> "
            f"{fmt_money(monto_total_preview, 'COP')} "
            f"<span style='color:#888;font-size:0.85rem;'>"
            f"(counter + prepagado)</span></div>",
            unsafe_allow_html=True,
        )

    observaciones = st.text_area(
        "Observaciones", height=80, placeholder="Notas adicionales (opcional)",
        value=editing_data.get("observaciones", "") or "",
        help="Notas adicionales (opcional).",
    )

    btn_label = "Guardar cambios" if editing else "Guardar factura"
    submitted = st.form_submit_button(btn_label)

if submitted:
    monto_total = round(monto_counter + monto_prepagado, 2)
    iva_factor = 1 + IVA_PORCENTAJE / 100.0
    monto_base = round(monto_total / iva_factor, 2)
    iva = round(monto_total - monto_base, 2)
    prepaid = monto_prepagado > 0

    if monto_total <= 0:
        st.error("El monto total (counter + prepagado) debe ser mayor a 0.")
    elif not rntl_mvnr.strip().isdigit():
        st.error("El numero de contrato debe ser solo digitos.")
    else:
        params = {
            "rntl_mvnr": int(rntl_mvnr.strip()),
            "sede_codigo": int(sede_map.get(sede_nombre, 0)),
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
            "capturado_por": username,
        }
        try:
            if editing:
                params["invoice_id"] = st.session_state["_editing_id"]
                execute_write("""
                    UPDATE operational.invoices SET
                        rntl_mvnr = :rntl_mvnr, sede_codigo = :sede_codigo,
                        sede_nombre = :sede_nombre, fecha_emision = :fecha_emision,
                        moneda = :moneda, numero_factura = :numero_factura,
                        numero_recibo = :numero_recibo, monto_base = :monto_base,
                        iva = :iva, monto_total = :monto_total,
                        monto_prepagado = :monto_prepagado, monto_counter = :monto_counter,
                        prepaid = :prepaid, observaciones = :observaciones,
                        capturado_por = :capturado_por
                    WHERE invoice_id = :invoice_id
                """, params)
                st.success(f"Factura #{params['invoice_id']} actualizada.")
                st.session_state["_editing_id"] = None
                st.session_state["_editing_data"] = {}
            else:
                execute_write("""
                    INSERT INTO operational.invoices
                      (rntl_mvnr, sede_codigo, sede_nombre, fecha_emision, moneda,
                       numero_factura, numero_recibo, monto_base, iva, monto_total,
                       monto_prepagado, monto_counter, prepaid, observaciones, capturado_por)
                    VALUES
                      (:rntl_mvnr, :sede_codigo, :sede_nombre, :fecha_emision, :moneda,
                       :numero_factura, :numero_recibo, :monto_base, :iva, :monto_total,
                       :monto_prepagado, :monto_counter, :prepaid, :observaciones, :capturado_por)
                """, params)
                tag = "prepagada" if prepaid else "no prepagada"
                st.success(f"Factura guardada — {sede_nombre} — contrato {rntl_mvnr} — "
                           f"{fmt_money(monto_total, 'COP')} ({tag}).")
                # Limpia el prefill del recordatorio para que el campo no
                # reaparezca con el contrato ya facturado en el proximo render.
                st.session_state.pop("_prefill_contrato", None)
            load_query.clear()
        except Exception as e:
            st.error(f"Error guardando: {e}")


st.markdown("---")


# =============================================================================
# 2. FACTURAS ABIERTAS (no finalizadas) — editable
# =============================================================================
section("Facturas abiertas (pendientes de finalizar)")

# LEFT JOIN a silver para mostrar fecha de entrega (handover) y devolucion.
# Las facturas casi siempre se crean ANTES de que el contrato llegue a silver
# (desfase de Redshift), asi que el join puede no encontrar fila: en ese caso
# entrega/devolucion quedan NULL y se muestran como "pendiente". 1:1 porque
# vw_rentals_resumen es 1 fila por contrato.
open_sql = f"""
    SELECT i.invoice_id, i.fecha_emision, i.sede_nombre, i.rntl_mvnr,
           i.numero_factura, i.numero_recibo,
           i.monto_total, i.monto_prepagado, i.monto_counter,
           i.observaciones, i.capturado_por, i.capturado_at,
           r.fecha_handover_real::date   AS fecha_entrega,
           r.fecha_devolucion_real::date AS fecha_devolucion
    FROM operational.invoices i
    LEFT JOIN silver.vw_rentals_resumen r ON r.numero_contrato = i.rntl_mvnr
    WHERE i.finalizada = FALSE {sede_where}
    -- Ordenadas por fecha de entrega (handover), mas reciente primero. Las
    -- "pendiente" (contrato aun no en silver -> sin entrega) van al final.
    ORDER BY r.fecha_handover_real DESC NULLS LAST, i.capturado_at DESC
"""
df_open = load_query(open_sql, sede_params if sede_params else {})

if df_open.empty:
    st.info("No hay facturas abiertas para tu sede.")
else:
    st.caption(f"{len(df_open)} facturas abiertas. Selecciona una para editar o finalizar.")

    open_w = [0.7, 1.6, 2.2, 1.4, 1.4, 1.6, 1.0, 1.1]
    head = st.columns(open_w)
    for col, label in zip(head, ["Factura", "Contrato", "Sede", "Entrega",
                                 "Devolucion", "Total", "", ""]):
        col.markdown(f"<span style='font-size:0.78rem;color:#888;"
                     f"text-transform:uppercase;'>{label}</span>",
                     unsafe_allow_html=True)

    for _, row in df_open.iterrows():
        inv_id = int(row["invoice_id"])
        contrato = int(row["rntl_mvnr"]) if pd.notna(row["rntl_mvnr"]) else "-"
        total = fmt_money(float(row["monto_total"]) if pd.notna(row["monto_total"]) else 0, "COP")
        sede = row["sede_nombre"] or "-"
        entrega = row["fecha_entrega"] if pd.notna(row["fecha_entrega"]) else "pendiente"
        devol = row["fecha_devolucion"] if pd.notna(row["fecha_devolucion"]) else "pendiente"

        cols = st.columns(open_w)
        cols[0].write(f"**#{inv_id}**")
        cols[1].write(f"{contrato}")
        cols[2].write(f"{sede}")
        cols[3].write(f"{entrega}")
        cols[4].write(f"{devol}")
        cols[5].write(f"{total}")

        if cols[6].button("Editar", key=f"edit_{inv_id}"):
            st.session_state["_editing_id"] = inv_id
            st.session_state["_editing_data"] = row.to_dict()
            st.rerun()

        if cols[7].button("Finalizar", key=f"fin_{inv_id}"):
            execute_write("""
                UPDATE operational.invoices
                SET finalizada = TRUE, finalizada_at = NOW(), finalizada_por = :user
                WHERE invoice_id = :id
            """, {"id": inv_id, "user": username})
            st.success(f"Factura #{inv_id} finalizada.")
            load_query.clear()
            st.rerun()


st.markdown("---")


# =============================================================================
# 2b. FACTURAS VENCIDAS (no finalizadas pero el vehiculo ya fue devuelto)
# =============================================================================
# Alerta para los asesores: el contrato ya cerro (fecha_devolucion_real en pasado)
# pero la factura sigue abierta. Probablemente se les olvido finalizarla.
section("Facturas vencidas (vehiculo devuelto sin finalizar)")

vencidas_sql = f"""
    SELECT i.invoice_id, i.rntl_mvnr, i.sede_nombre, i.fecha_emision,
           i.numero_factura, i.numero_recibo, i.monto_total,
           r.fecha_handover_real::date AS fecha_entrega,
           r.fecha_devolucion_real::date AS fecha_devolucion,
           (CURRENT_DATE - r.fecha_devolucion_real::date) AS dias_vencida,
           i.capturado_por
    FROM operational.invoices i
    INNER JOIN silver.vw_rentals_resumen r ON r.numero_contrato = i.rntl_mvnr
    WHERE i.finalizada = FALSE
      AND r.fecha_devolucion_real IS NOT NULL
      AND r.fecha_devolucion_real::date < CURRENT_DATE
      {sede_where}
    ORDER BY r.fecha_devolucion_real::date ASC
"""
df_vencidas = load_query(vencidas_sql, sede_params if sede_params else {})

if df_vencidas.empty:
    st.success("No hay facturas vencidas. Todas las facturas abiertas corresponden a contratos aun activos.")
else:
    st.error(
        f"{len(df_vencidas)} factura(s) abierta(s) cuyo vehiculo ya fue devuelto. "
        f"Por favor finalicelas (boton 'Finalizar' en la seccion de facturas abiertas)."
    )
    vencidas_view = df_vencidas.copy()
    vencidas_view["monto_total"] = vencidas_view["monto_total"].apply(
        lambda v: fmt_money(v, "COP") if pd.notna(v) else "-")
    vencidas_view = vencidas_view.rename(columns={
        "invoice_id": "ID",
        "rntl_mvnr": "Contrato",
        "sede_nombre": "Sede",
        "fecha_emision": "Fecha emision",
        "numero_factura": "Numero factura",
        "numero_recibo": "Numero recibo",
        "monto_total": "Monto (COP)",
        "fecha_entrega": "Entrega",
        "fecha_devolucion": "Devolucion",
        "dias_vencida": "Dias vencida",
        "capturado_por": "Capturado por",
    })
    st.dataframe(vencidas_view, use_container_width=True, hide_index=True)


st.markdown("---")


# =============================================================================
# 3. VALIDACION: facturas finalizadas vs silver (alarma si hay diferencia)
# =============================================================================
section("Validacion de facturas finalizadas")
st.caption(
    f"Compara el monto total registrado en la factura contra el total calculado "
    f"por el sistema (charges x TRM Banrep). Tolerancia: {fmt_money(VALIDATION_TOLERANCE_COP, 'COP')}. "
    f"Facturas cuyo contrato aun no esta en silver (pendiente de refresh) se muestran aparte."
)

val_sql = f"""
    SELECT i.invoice_id, i.rntl_mvnr, i.sede_nombre, i.fecha_emision,
           i.monto_total AS factura_cop,
           r.total_con_iva_usd AS total_usd,
           t.trm_cop_per_usd AS trm_usada,
           CASE WHEN r.numero_contrato IS NOT NULL AND t.trm_cop_per_usd IS NOT NULL
                THEN ROUND(r.total_con_iva_usd * t.trm_cop_per_usd, 0)
                ELSE NULL END AS sistema_cop,
           CASE WHEN r.numero_contrato IS NOT NULL AND t.trm_cop_per_usd IS NOT NULL
                THEN i.monto_total - ROUND(r.total_con_iva_usd * t.trm_cop_per_usd, 0)
                ELSE NULL END AS diferencia,
           CASE WHEN r.numero_contrato IS NULL THEN TRUE ELSE FALSE END AS pendiente_silver
    FROM operational.invoices i
    LEFT JOIN silver.vw_rentals_resumen r ON r.numero_contrato = i.rntl_mvnr
    LEFT JOIN silver.dim_trm_diaria t ON t.fecha = r.fecha_handover_real::date
    WHERE i.finalizada = TRUE {sede_where}
    ORDER BY
        CASE WHEN r.numero_contrato IS NULL THEN 0 ELSE 1 END,
        ABS(COALESCE(i.monto_total - ROUND(COALESCE(r.total_con_iva_usd, 0)
                     * COALESCE(t.trm_cop_per_usd, 0), 0), 0)) DESC
"""
df_val = load_query(val_sql, sede_params if sede_params else {})

if df_val.empty:
    st.info("No hay facturas finalizadas para validar.")
else:
    for col in ("factura_cop", "sistema_cop", "diferencia", "total_usd", "trm_usada"):
        df_val[col] = pd.to_numeric(df_val[col], errors="coerce")

    # Split into 3 groups:
    # 1. Pending silver (contract not in system yet — pipeline hasn't run)
    # 2. Mismatch (contract in silver, difference > tolerance)
    # 3. OK (contract in silver, difference <= tolerance)
    df_pending = df_val[df_val["pendiente_silver"] == True].copy()
    df_validated = df_val[df_val["pendiente_silver"] == False].copy()
    df_validated["diferencia"] = df_validated["diferencia"].fillna(0)
    df_validated["sistema_cop"] = df_validated["sistema_cop"].fillna(0)
    df_mismatch = df_validated[df_validated["diferencia"].abs() > VALIDATION_TOLERANCE_COP].copy()
    df_ok = df_validated[df_validated["diferencia"].abs() <= VALIDATION_TOLERANCE_COP].copy()

    # --- Pending: contract not in silver yet ---
    if not df_pending.empty:
        st.warning(
            f"{len(df_pending)} facturas finalizadas cuyo contrato aun no esta en silver. "
            f"Se validaran automaticamente despues del proximo refresh del pipeline."
        )
        pending_view = df_pending[["invoice_id", "rntl_mvnr", "sede_nombre",
                                    "fecha_emision", "factura_cop"]].copy()
        pending_view["factura_cop"] = pending_view["factura_cop"].apply(
            lambda v: fmt_money(v, "COP") if pd.notna(v) else "-")
        pending_view = pending_view.rename(columns={
            "invoice_id": "ID", "rntl_mvnr": "Contrato", "sede_nombre": "Sede",
            "fecha_emision": "Fecha", "factura_cop": "Factura (COP)",
        })
        st.dataframe(pending_view, use_container_width=True, hide_index=True)

    if not df_mismatch.empty:
        st.error(f"{len(df_mismatch)} facturas con diferencia mayor a {fmt_money(VALIDATION_TOLERANCE_COP, 'COP')}:")
        for _, row in df_mismatch.iterrows():
            inv_id = int(row["invoice_id"])
            contrato = int(row["rntl_mvnr"]) if pd.notna(row["rntl_mvnr"]) else "-"
            dif = float(row["diferencia"])

            # El signo $ activa el modo LaTeX de Streamlit (dos $ = math mode),
            # lo que rompe el HTML intermedio. Lo escapamos como &#36; para que
            # se muestre literal sin disparar KaTeX.
            factura_html = fmt_money(row["factura_cop"], "COP").replace("$", "&#36;")
            sistema_html = fmt_money(row["sistema_cop"], "COP").replace("$", "&#36;")
            dif_html = fmt_money(dif, "COP").replace("$", "&#36;")

            cols = st.columns([1, 2, 2, 2, 2, 1])
            cols[0].write(f"**#{inv_id}**")
            cols[1].write(f"Contrato: {contrato}")
            cols[2].markdown(
                f"<b>Factura:</b> {factura_html} &nbsp;|&nbsp; "
                f"<b>Sistema:</b> {sistema_html}",
                unsafe_allow_html=True,
            )
            color = "#d32f2f" if abs(dif) > 5000 else "#f57c00"
            cols[3].markdown(
                f"<span style='color:{color};font-weight:bold;'>"
                f"Diferencia: {dif_html}</span>",
                unsafe_allow_html=True,
            )
            cols[4].write(f"TRM: {row['trm_usada']:,.2f}")

            if cols[5].button("Reabrir", key=f"reopen_{inv_id}"):
                execute_write("""
                    UPDATE operational.invoices
                    SET finalizada = FALSE, finalizada_at = NULL, finalizada_por = NULL
                    WHERE invoice_id = :id
                """, {"id": inv_id})
                st.warning(f"Factura #{inv_id} reabierta para correccion.")
                load_query.clear()
                st.rerun()

    if not df_ok.empty:
        st.success(f"{len(df_ok)} facturas finalizadas cuadran con el sistema.")
        view = df_ok[["invoice_id", "rntl_mvnr", "sede_nombre", "fecha_emision",
                       "factura_cop", "sistema_cop", "diferencia"]].copy()
        view["factura_cop"] = view["factura_cop"].apply(lambda v: fmt_money(v, "COP"))
        view["sistema_cop"] = view["sistema_cop"].apply(lambda v: fmt_money(v, "COP"))
        view["diferencia"] = view["diferencia"].apply(lambda v: fmt_money(v, "COP"))
        view = view.rename(columns={
            "invoice_id": "ID", "rntl_mvnr": "Contrato", "sede_nombre": "Sede",
            "fecha_emision": "Fecha", "factura_cop": "Factura (COP)",
            "sistema_cop": "Sistema (COP)", "diferencia": "Diferencia",
        })
        st.dataframe(view, use_container_width=True, hide_index=True)


st.markdown("---")


# =============================================================================
# 4. FACTURAS FINALIZADAS (historial)
# =============================================================================
section("Historial de facturas finalizadas")
fin_sql = f"""
    SELECT i.invoice_id, i.fecha_emision, i.sede_nombre, i.rntl_mvnr,
           i.numero_factura, i.numero_recibo,
           i.monto_total, i.monto_prepagado, i.monto_counter, i.prepaid,
           i.finalizada_por, i.finalizada_at
    FROM operational.invoices i
    WHERE i.finalizada = TRUE {sede_where}
    ORDER BY i.finalizada_at DESC
    LIMIT 50
"""
df_fin = load_query(fin_sql, sede_params if sede_params else {})
if df_fin.empty:
    st.info("No hay facturas finalizadas.")
else:
    st.dataframe(df_fin, use_container_width=True, hide_index=True)
    st.caption(f"Mostrando ultimas {len(df_fin)} facturas finalizadas.")

    # -----------------------------------------------------------------
    # ADMIN ONLY: Reabrir cualquier factura finalizada por ID
    # -----------------------------------------------------------------
    # Antes hacian este proceso por SQL directo en Supabase. Ahora desde UI.
    if user_is_admin:
        st.markdown("##### Reabrir factura (admin)")
        st.caption(
            "Si finalizaron una factura por error, ingresa el ID aqui y se reabre "
            "para que el asesor pueda corregirla y volver a finalizarla."
        )
        admin_cols = st.columns([2, 2, 1])
        reopen_id_str = admin_cols[0].text_input(
            "ID de factura a reabrir",
            key="_admin_reopen_id",
            placeholder="ej. 91",
        )
        admin_confirm = admin_cols[1].checkbox(
            "Confirmo que quiero reabrirla",
            key="_admin_reopen_confirm",
        )
        if admin_cols[2].button("Reabrir", key="_admin_reopen_btn", type="primary"):
            try:
                reopen_id = int(reopen_id_str.strip())
            except (ValueError, AttributeError):
                st.error("Ingresa un ID valido (numero entero).")
            else:
                if not admin_confirm:
                    st.error("Marca la casilla de confirmacion antes de reabrir.")
                else:
                    # Verificar que existe y esta finalizada
                    check = load_query(
                        "SELECT invoice_id, rntl_mvnr, sede_nombre, finalizada "
                        "FROM operational.invoices WHERE invoice_id = :id",
                        {"id": reopen_id},
                    )
                    if check.empty:
                        st.error(f"No existe factura con ID {reopen_id}.")
                    elif not bool(check.iloc[0]["finalizada"]):
                        st.warning(
                            f"La factura #{reopen_id} ya esta abierta. "
                            f"No requiere accion."
                        )
                    else:
                        execute_write("""
                            UPDATE operational.invoices
                            SET finalizada = FALSE,
                                finalizada_at = NULL,
                                finalizada_por = NULL
                            WHERE invoice_id = :id
                        """, {"id": reopen_id})
                        row = check.iloc[0]
                        st.success(
                            f"Factura #{reopen_id} reabierta "
                            f"(contrato {int(row['rntl_mvnr'])}, sede {row['sede_nombre']})."
                        )
                        load_query.clear()
                        st.rerun()


# =============================================================================
# 0. RECORDATORIO: contratos con handover reciente sin factura creada
# =============================================================================
# Renderizado al final (dentro de reminder_slot, que esta arriba del form) para
# que refleje los inserts hechos en este mismo run tras load_query.clear().
# El filtro por sede es server-side: un usuario sede NUNCA recibe contratos de
# otra sucursal, ni manipulando la URL, porque el WHERE va en el SQL.
with reminder_slot:
    if user_is_admin or "*" in user_branches:
        sede_opts = ["Todas las sedes"] + list(sede_map.keys())
        sede_sel = st.selectbox(
            "Sede (pendientes)", options=sede_opts, index=0, key="_rem_sede",
            help="Filtra los contratos pendientes de facturar por sede.",
        )
        if sede_sel == "Todas las sedes":
            rem_where = ""
            rem_params = {"fecha_inicio": FECHA_INICIO_RECORDATORIO}
        else:
            rem_where = "AND r.sede_handover = :sede_sel"
            rem_params = {"fecha_inicio": FECHA_INICIO_RECORDATORIO,
                          "sede_sel": sede_sel}
    else:
        rem_where = "AND r.sede_handover = :user_sede"
        rem_params = {"fecha_inicio": FECHA_INICIO_RECORDATORIO,
                      "user_sede": user_branches[0] if user_branches else ""}

    rem_sql = f"""
        SELECT r.numero_contrato,
               r.fecha_handover_real::date AS fecha_handover,
               r.fecha_devolucion_real::date AS fecha_devolucion,
               r.placa,
               r.vehiculo,
               r.sede_handover,
               r.operador_handover_codigo AS asesor,
               -- Total en COP via TRM Banrep del dia de la entrega (regla #6).
               ROUND(r.total_con_iva_usd * t.trm_cop_per_usd, 0) AS total_cop
        FROM silver.vw_rentals_resumen r
        LEFT JOIN operational.invoices i ON i.rntl_mvnr = r.numero_contrato
        LEFT JOIN silver.dim_trm_diaria t ON t.fecha = r.fecha_handover_real::date
        WHERE r.fecha_handover_real::date >= :fecha_inicio
          -- Solo rentas YA entregadas: el handover debe haber ocurrido. Sin
          -- este tope, contratos a futuro (reservas/placeholders sin vehiculo
          -- asignado, asesor 7777777) aparecerian como "pendientes". No se
          -- puede facturar una renta que aun no empieza. Zona Colombia (UTC-5).
          AND r.fecha_handover_real::date <= ((NOW() AT TIME ZONE 'America/Bogota')::date)
          -- Excluir registros administrativos con vehiculo dummy 99999999
          -- (regla #9): status-match de competidores y similares. Llegan con
          -- placa/vehiculo vacios, operador 7777777 y revenue 0; no son rentas
          -- reales y no se facturan. El placeholder real tiene placa vacia.
          AND COALESCE(TRIM(r.placa), '') <> ''
          AND i.invoice_id IS NULL
          {rem_where}
        ORDER BY r.fecha_handover_real DESC
    """
    df_rem = load_query(rem_sql, rem_params)
    n_pend = len(df_rem)

    if n_pend == 0:
        st.markdown(
            "<div style='background:#e8f5e9;padding:10px 14px;border-radius:4px;"
            "border-left:3px solid #43a047;margin:4px 0 12px 0;color:#2e7d32;"
            "font-size:0.95rem;'>Estas al dia con las facturas. No hay contratos "
            f"pendientes con handover desde {FECHA_INICIO_RECORDATORIO}.</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"<div style='background:#fff3e0;padding:10px 16px;border-radius:4px;"
            f"border-left:4px solid #ff6900;margin:4px 0 4px 0;color:#333;'>"
            f"<span style='font-size:1.05rem;font-weight:700;color:#e55a00;'>"
            f"Pendientes de crear factura ({n_pend})</span><br>"
            f"<span style='font-size:0.88rem;color:#666;'>Contratos entregados "
            f"desde {FECHA_INICIO_RECORDATORIO} (entrega ya realizada) sin "
            f"factura creada.</span></div>",
            unsafe_allow_html=True,
        )

        col_widths = [2, 3, 2, 2, 3, 2, 2, 2]
        head = st.columns(col_widths)
        for col, label in zip(
            head, ["Contrato", "Sede", "Entrega", "Placa", "Vehiculo",
                   "Asesor", "Total", ""]
        ):
            col.markdown(f"<span style='font-size:0.78rem;color:#888;"
                         f"text-transform:uppercase;'>{label}</span>",
                         unsafe_allow_html=True)

        for _, row in df_rem.iterrows():
            contrato = int(row["numero_contrato"])
            cols = st.columns(col_widths)
            cols[0].write(f"{contrato}")
            cols[1].write(f"{row['sede_handover'] or '-'}")
            cols[2].write(f"{row['fecha_handover']}")
            cols[3].write(f"{row['placa'] or '-'}")
            cols[4].write(f"{row['vehiculo'] or '-'}")
            cols[5].write(f"{int(row['asesor']) if pd.notna(row['asesor']) else '-'}")
            cols[6].write(fmt_money(row["total_cop"], "COP"))
            if cols[7].button("Crear factura", key=f"rem_create_{contrato}"):
                st.session_state["_prefill_contrato"] = str(contrato)
                st.session_state["_editing_id"] = None
                st.session_state["_editing_data"] = {}
                st.rerun()

    st.markdown("---")
