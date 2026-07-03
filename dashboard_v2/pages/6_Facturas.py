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
    fmt_money, render_trm_today_sidebar, xlsx_download_button,
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
# Self-healing migration: asegurar columnas de revision.
# @st.cache_resource -> corre 1 vez por instancia de Streamlit. Idempotente
# gracias a IF NOT EXISTS, asi que si ya existen es no-op.
# =============================================================================
@st.cache_resource
def _ensure_revisada_columns():
    try:
        execute_write("""
            ALTER TABLE operational.invoices
                ADD COLUMN IF NOT EXISTS revisada     BOOLEAN NOT NULL DEFAULT FALSE,
                ADD COLUMN IF NOT EXISTS revisada_at  TIMESTAMPTZ,
                ADD COLUMN IF NOT EXISTS revisada_por TEXT
        """, {})
    except Exception:
        # Si falla (permisos, etc.), no bloqueamos la pagina. El SELECT con
        # COALESCE(revisada, FALSE) y las columnas nullables lo manejan.
        pass

_ensure_revisada_columns()


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
        contrato_int = int(rntl_mvnr.strip())

        # Pre-flight: regla 1:1 contrato -> factura. Solo aplica al crear.
        # Check global (sin filtro de sede) porque rntl_mvnr es global en Sixt:
        # un contrato facturado en sede A no se puede re-facturar en sede B.
        existing_dup = None
        if not editing:
            existing = load_query(
                "SELECT invoice_id, sede_nombre, finalizada "
                "FROM operational.invoices "
                "WHERE rntl_mvnr = :c ORDER BY invoice_id",
                {"c": contrato_int},
            )
            if not existing.empty:
                existing_dup = existing

        if existing_dup is not None:
            if user_is_admin or "*" in user_branches:
                # Admin ve detalle completo (IDs, sede, status) para decidir.
                ids_list = ", ".join(
                    f"#{int(r['invoice_id'])} "
                    f"({'cerrada' if r['finalizada'] else 'abierta'}, "
                    f"sede {r['sede_nombre']})"
                    for _, r in existing_dup.iterrows()
                )
                st.error(
                    f"Ya existe factura(s) para el contrato {contrato_int}: "
                    f"{ids_list}. Edita la existente o eliminala con el "
                    f"widget de admin abajo. No se permiten duplicados (1 factura = 1 contrato)."
                )
            else:
                # Sede user: no revelar sede de la factura existente si es de otra sede.
                own_invoices = existing_dup[
                    existing_dup["sede_nombre"] == user_branches[0]
                ]
                if not own_invoices.empty:
                    ids_list = ", ".join(
                        f"#{int(r['invoice_id'])} "
                        f"({'cerrada' if r['finalizada'] else 'abierta'})"
                        for _, r in own_invoices.iterrows()
                    )
                    st.error(
                        f"Ya existe factura para el contrato {contrato_int}: "
                        f"{ids_list}. Edita la existente abajo. "
                        f"No se permiten duplicados."
                    )
                else:
                    st.error(
                        f"Ya existe factura para el contrato {contrato_int} "
                        f"en otra sede. Si crees que es un error, contacta al admin. "
                        f"No se permiten duplicados."
                    )
        else:
            params = {
                "rntl_mvnr": contrato_int,
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
# 2. FACTURAS ABIERTAS — vista unificada con TRM, sistema esperado y cuadre inline
# =============================================================================
# Una sola tabla con TODO lo que el asesor necesita ver antes de finalizar:
#   - Datos basicos (contrato, sede, entrega, devolucion, total)
#   - TRM Banrep del dia de entrega
#   - Monto esperado por sistema (charges silver x TRM)
#   - Diferencia + estado (cuadra / sobre tolerancia / pendiente silver / vencida)
# Vencidas (vehiculo devuelto sin finalizar) salen marcadas con icono y color.
section("Facturas abiertas (pendientes de finalizar)")
st.caption(
    f"Cada factura muestra TRM Banrep del dia de entrega, monto calculado por el "
    f"sistema y diferencia. Tolerancia: {fmt_money(VALIDATION_TOLERANCE_COP, 'COP')}. "
    f"Si el vehiculo ya fue devuelto pero la factura sigue abierta, sale marcada como 'Vencida'."
)

open_sql = f"""
    WITH dups AS (
        SELECT i.rntl_mvnr, ARRAY_AGG(i.invoice_id ORDER BY i.invoice_id) AS all_ids
        FROM operational.invoices i
        WHERE TRUE {sede_where}
        GROUP BY i.rntl_mvnr
        HAVING COUNT(*) > 1
    )
    SELECT i.invoice_id, i.fecha_emision, i.sede_nombre, i.rntl_mvnr,
           i.numero_factura, i.numero_recibo,
           i.monto_total, i.monto_prepagado, i.monto_counter,
           i.observaciones, i.capturado_por, i.capturado_at,
           r.fecha_handover_real::date   AS fecha_entrega,
           r.fecha_devolucion_real::date AS fecha_devolucion,
           r.total_con_iva_usd           AS total_usd,
           t.trm_cop_per_usd             AS trm,
           CASE WHEN r.numero_contrato IS NOT NULL AND t.trm_cop_per_usd IS NOT NULL
                THEN ROUND(r.total_con_iva_usd * t.trm_cop_per_usd, 0)
                ELSE NULL END             AS sistema_cop,
           CASE WHEN r.numero_contrato IS NOT NULL AND t.trm_cop_per_usd IS NOT NULL
                THEN i.monto_total - ROUND(r.total_con_iva_usd * t.trm_cop_per_usd, 0)
                ELSE NULL END             AS diferencia,
           CASE WHEN r.numero_contrato IS NULL THEN TRUE ELSE FALSE END
                                          AS pendiente_silver,
           d.all_ids                      AS dup_all_ids
    FROM operational.invoices i
    LEFT JOIN silver.vw_rentals_resumen r ON r.numero_contrato = i.rntl_mvnr
    LEFT JOIN silver.dim_trm_diaria t ON t.fecha = r.fecha_handover_real::date
    LEFT JOIN dups d ON d.rntl_mvnr = i.rntl_mvnr
    WHERE i.finalizada = FALSE {sede_where}
    ORDER BY r.fecha_handover_real DESC NULLS LAST, i.capturado_at DESC
"""
df_open = load_query(open_sql, sede_params if sede_params else {})

if df_open.empty:
    st.info("No hay facturas abiertas para tu sede.")
else:
    # Convertir columnas numericas
    for col in ("monto_total", "total_usd", "trm", "sistema_cop", "diferencia"):
        df_open[col] = pd.to_numeric(df_open[col], errors="coerce")

    # Determinar vencidas (vehiculo devuelto pero factura abierta)
    today = dt.date.today()
    df_open["es_vencida"] = df_open["fecha_devolucion"].apply(
        lambda v: pd.notna(v) and v < today
    )

    # Summary line
    n_vencidas = int(df_open["es_vencida"].sum())
    n_pendientes = int(df_open["pendiente_silver"].sum())
    diff_abs = df_open["diferencia"].abs()
    n_sobre_tol = int(((diff_abs > VALIDATION_TOLERANCE_COP) &
                       ~df_open["pendiente_silver"]).sum())

    summary_parts = [f"{len(df_open)} factura(s) abierta(s)"]
    if n_vencidas > 0:
        summary_parts.append(f"{n_vencidas} vencida(s)")
    if n_sobre_tol > 0:
        summary_parts.append(f"{n_sobre_tol} sobre tolerancia")
    if n_pendientes > 0:
        summary_parts.append(f"{n_pendientes} pendiente(s) silver")
    st.caption(" · ".join(summary_parts))

    # Header de columnas: ID | Contrato | Sede | Entrega | Devol | Total | Editar | Finalizar
    open_w = [0.7, 1.6, 2.2, 1.3, 1.3, 1.6, 1.0, 1.1]
    head = st.columns(open_w)
    for col, label in zip(head, ["Factura", "Contrato", "Sede", "Entrega",
                                 "Devolucion", "Total", "", ""]):
        col.markdown(f"<span style='font-size:0.78rem;color:#888;"
                     f"text-transform:uppercase;'>{label}</span>",
                     unsafe_allow_html=True)

    for _, row in df_open.iterrows():
        inv_id = int(row["invoice_id"])
        contrato = int(row["rntl_mvnr"]) if pd.notna(row["rntl_mvnr"]) else "-"
        total = fmt_money(float(row["monto_total"])
                          if pd.notna(row["monto_total"]) else 0, "COP")
        sede = row["sede_nombre"] or "-"
        entrega = str(row["fecha_entrega"]) if pd.notna(row["fecha_entrega"]) else "pendiente"
        devol_raw = row["fecha_devolucion"]
        devol_display = str(devol_raw) if pd.notna(devol_raw) else "pendiente"
        es_vencida = bool(row["es_vencida"])

        # --- Fila principal ---
        cols = st.columns(open_w)
        cols[0].write(f"**#{inv_id}**")
        cols[1].write(f"{contrato}")
        cols[2].write(f"{sede}")
        cols[3].write(f"{entrega}")
        if es_vencida:
            cols[4].markdown(
                f"<span style='color:#d32f2f;font-weight:bold;'>"
                f"{devol_display}</span>",
                unsafe_allow_html=True,
            )
        else:
            cols[4].write(devol_display)
        cols[5].write(total)

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

        # --- Sub-linea con TRM + sistema esperado + diferencia + estado ---
        # El signo $ activa LaTeX en Streamlit; escapamos a &#36; para que
        # se muestre literal.
        sub_parts = []

        if row["pendiente_silver"]:
            sub_parts.append(
                "<span style='color:#999;'>Contrato aun no esta en silver "
                "- se validara despues del proximo refresh del pipeline.</span>"
            )
        elif pd.notna(row["diferencia"]):
            trm_val = float(row["trm"]) if pd.notna(row["trm"]) else 0
            sis_val = float(row["sistema_cop"]) if pd.notna(row["sistema_cop"]) else 0
            dif_val = float(row["diferencia"])
            dif_abs = abs(dif_val)

            sistema_html = fmt_money(sis_val, "COP").replace("$", "&#36;")
            dif_html = fmt_money(dif_val, "COP").replace("$", "&#36;")

            sub_parts.append(f"TRM Banrep: {trm_val:,.2f}")
            sub_parts.append(f"Sistema: {sistema_html}")
            sub_parts.append(f"Diferencia: {dif_html}")

            if dif_abs <= VALIDATION_TOLERANCE_COP:
                sub_parts.append(
                    "<span style='color:#2e7d32;font-weight:bold;'>Cuadra</span>"
                )
            else:
                color = "#d32f2f" if dif_abs > 5000 else "#f57c00"
                sub_parts.append(
                    f"<span style='color:{color};font-weight:bold;'>"
                    f"Sobre tolerancia</span>"
                )
        else:
            # No hay info para validar (probablemente sin TRM por feriado/etc)
            sub_parts.append(
                "<span style='color:#999;'>Sin datos suficientes para validar</span>"
            )

        if es_vencida:
            sub_parts.append(
                "<span style='color:#d32f2f;font-weight:bold;'>Vencida</span>"
            )

        # Indicador de duplicado: si este contrato tiene otras facturas en
        # operational.invoices, mostrar IDs de las hermanas (regla 1:1 violada).
        dup_all = row.get("dup_all_ids")
        if isinstance(dup_all, (list, tuple)):
            others = [int(x) for x in dup_all if int(x) != inv_id]
            if others:
                others_str = ", ".join(f"#{i}" for i in others)
                sub_parts.append(
                    f"<span style='color:#d32f2f;font-weight:bold;'>"
                    f"DUPLICADO con {others_str}</span>"
                )

        st.markdown(
            f"<div style='font-size:0.82rem;color:#666;margin-left:0.5rem;"
            f"margin-top:-0.5rem;margin-bottom:0.4rem;'>"
            f"{' · '.join(sub_parts)}"
            f"</div>",
            unsafe_allow_html=True,
        )

        # Separador entre facturas
        st.markdown(
            "<hr style='margin:0.3rem 0;border:none;border-top:1px solid #eee;'>",
            unsafe_allow_html=True,
        )


st.markdown("---")


# =============================================================================
# 4. FACTURAS FINALIZADAS (historial)
# =============================================================================
section("Historial de facturas finalizadas")
st.caption(
    "Vista retrospectiva. Muestra que se cobro, que decia el contrato segun "
    "silver, la diferencia, la TRM oficial Banrep del dia de entrega y la "
    "TRM efectivamente usada (deducida del monto cobrado)."
)

# Filtro por rango de fechas (default: ultimos 90 dias).
# Antes habia un LIMIT 50 que ocultaba facturas viejas si en los ultimos
# dias se finalizaban muchas. El filtro por fecha es mas predecible.
_today = dt.date.today()
_default_desde = _today - dt.timedelta(days=90)
hist_cols = st.columns([1, 1, 4])
hist_desde = hist_cols[0].date_input(
    "Desde (fecha entrega contrato)",
    value=_default_desde,
    key="_hist_desde",
    help="Filtra por fecha de handover del contrato. Default: ultimos 90 dias.",
)
hist_hasta = hist_cols[1].date_input(
    "Hasta (fecha entrega contrato)",
    value=_today,
    key="_hist_hasta",
    help="Hasta esta fecha de handover del contrato.",
)

# JOIN a silver + dim_trm_diaria para validar contra TRM oficial.
# TRM usada se deduce: si monto_cop = usd * trm, entonces trm_usada = monto_cop / usd.
# Esto permite ver si el asesor uso una TRM distinta (vieja, redondeada, etc.).
# CTE `dups`: detecta contratos con >1 factura (regla 1:1 violada).
# Filtrado por sede_where para que sede users solo vean duplicados de su sede.
# Filtramos por fecha de handover (silver). Si el contrato no esta en silver
# (factura creada antes del pipeline refresh), incluimos la factura igual
# basados en fecha_emision para no perderla del historial.
fin_sql = f"""
    WITH dups AS (
        SELECT i.rntl_mvnr, ARRAY_AGG(i.invoice_id ORDER BY i.invoice_id) AS all_ids
        FROM operational.invoices i
        WHERE TRUE {sede_where}
        GROUP BY i.rntl_mvnr
        HAVING COUNT(*) > 1
    )
    SELECT i.invoice_id, i.fecha_emision, i.sede_nombre, i.rntl_mvnr,
           i.numero_factura, i.numero_recibo,
           i.monto_total, i.monto_prepagado, i.monto_counter, i.prepaid,
           i.finalizada_por, i.finalizada_at,
           COALESCE(i.revisada, FALSE) AS revisada,
           i.revisada_at, i.revisada_por,
           r.fecha_handover_real::date AS fecha_entrega,
           r.total_con_iva_usd         AS total_usd,
           t.trm_cop_per_usd           AS trm_oficial,
           CASE WHEN r.total_con_iva_usd IS NOT NULL AND t.trm_cop_per_usd IS NOT NULL
                THEN ROUND(r.total_con_iva_usd * t.trm_cop_per_usd, 0)
                ELSE NULL END           AS sistema_cop,
           CASE WHEN r.total_con_iva_usd IS NOT NULL AND t.trm_cop_per_usd IS NOT NULL
                THEN i.monto_total - ROUND(r.total_con_iva_usd * t.trm_cop_per_usd, 0)
                ELSE NULL END           AS diferencia,
           CASE WHEN r.total_con_iva_usd IS NOT NULL AND r.total_con_iva_usd > 0
                THEN ROUND((i.monto_total / r.total_con_iva_usd)::numeric, 2)
                ELSE NULL END           AS trm_usada_calculada,
           d.all_ids                    AS dup_all_ids
    FROM operational.invoices i
    LEFT JOIN silver.vw_rentals_resumen r ON r.numero_contrato = i.rntl_mvnr
    LEFT JOIN silver.dim_trm_diaria t ON t.fecha = r.fecha_handover_real::date
    LEFT JOIN dups d ON d.rntl_mvnr = i.rntl_mvnr
    WHERE i.finalizada = TRUE {sede_where}
      AND (
            -- Si esta en silver: filtra por handover del contrato
            (r.fecha_handover_real::date BETWEEN :hist_desde AND :hist_hasta)
            -- Si NO esta en silver: filtra por fecha de emision (para no perderla)
            OR (r.fecha_handover_real IS NULL
                AND i.fecha_emision BETWEEN :hist_desde AND :hist_hasta)
      )
    ORDER BY i.finalizada_at DESC
"""
_fin_params = {"hist_desde": hist_desde, "hist_hasta": hist_hasta}
if sede_params:
    _fin_params.update(sede_params)
df_fin = load_query(fin_sql, _fin_params)
if df_fin.empty:
    st.info("No hay facturas finalizadas.")
else:
    # Diferencia entre TRM usada y TRM oficial (cuanto se desvio el asesor)
    df_fin["diff_trm"] = df_fin["trm_usada_calculada"] - df_fin["trm_oficial"]

    # Duplicados: dup_all_ids viene como lista (o None si no hay duplicados).
    # Mostramos las OTRAS facturas que comparten contrato (excluyendo self).
    def _fmt_dups(all_ids, self_id):
        if not isinstance(all_ids, (list, tuple)):
            return "-"
        others = [int(x) for x in all_ids if int(x) != int(self_id)]
        if not others:
            return "-"
        return "Dup con " + ", ".join(f"#{i}" for i in others)

    df_fin["duplicados"] = df_fin.apply(
        lambda r: _fmt_dups(r.get("dup_all_ids"), r["invoice_id"]), axis=1
    )

    n_dups = int((df_fin["duplicados"] != "-").sum())
    if n_dups > 0:
        st.warning(
            f"Se detectaron {n_dups} factura(s) duplicada(s) — mismo contrato "
            f"con multiples facturas. Revisar columna 'Duplicados' y eliminar "
            f"las que sobran (regla 1:1)."
        )

    # Vista formateada. La columna 'Revisada' es CHECKBOX editable — cuando
    # el usuario la marca, guardamos revisada=TRUE + audit trail (quien/cuando).
    view = df_fin[[
        "invoice_id", "revisada", "fecha_emision", "sede_nombre", "rntl_mvnr",
        "duplicados", "numero_factura", "numero_recibo",
        "fecha_entrega",
        "monto_total", "sistema_cop", "diferencia",
        "trm_oficial", "trm_usada_calculada", "diff_trm",
        "finalizada_por", "finalizada_at",
        "revisada_por", "revisada_at",
    ]].copy()

    # revisada: asegurar bool (viene de Postgres, podria ser None si columna nueva)
    view["revisada"] = view["revisada"].fillna(False).astype(bool)

    # Formato de moneda COP
    for col in ("monto_total", "sistema_cop", "diferencia"):
        view[col] = view[col].apply(
            lambda v: fmt_money(v, "COP") if pd.notna(v) else "-"
        )
    # TRM con 2 decimales
    for col in ("trm_oficial", "trm_usada_calculada", "diff_trm"):
        view[col] = view[col].apply(
            lambda v: f"{v:,.2f}" if pd.notna(v) else "-"
        )
    # finalizada_at / revisada_at: solo fecha+hora bonita
    view["finalizada_at"] = pd.to_datetime(
        view["finalizada_at"], errors="coerce"
    ).dt.strftime("%Y-%m-%d %H:%M")
    view["revisada_at"] = pd.to_datetime(
        view["revisada_at"], errors="coerce"
    ).dt.strftime("%Y-%m-%d %H:%M").fillna("-")
    view["revisada_por"] = view["revisada_por"].fillna("-")

    view = view.rename(columns={
        "invoice_id": "ID",
        "revisada": "Revisada",
        "fecha_emision": "Fecha emision",
        "sede_nombre": "Sede",
        "rntl_mvnr": "Contrato",
        "duplicados": "Duplicados",
        "numero_factura": "Num factura",
        "numero_recibo": "Num recibo",
        "fecha_entrega": "Entrega",
        "monto_total": "Total cobrado (COP)",
        "sistema_cop": "Sistema (COP)",
        "diferencia": "Diferencia (COP)",
        "trm_oficial": "TRM oficial",
        "trm_usada_calculada": "TRM usada",
        "diff_trm": "Δ TRM",
        "finalizada_por": "Finalizada por",
        "finalizada_at": "Finalizada en",
        "revisada_por": "Revisada por",
        "revisada_at": "Revisada en",
    })

    # data_editor: solo 'Revisada' es editable; el resto disabled.
    # Cuando el usuario marca/desmarca el checkbox, detectamos el cambio,
    # persistimos en DB con audit trail, invalidamos cache y hacemos rerun.
    editable_cols = ["Revisada"]
    disabled_cols = [c for c in view.columns if c not in editable_cols]

    edited_view = st.data_editor(
        view,
        column_config={
            "Revisada": st.column_config.CheckboxColumn(
                "Revisada",
                help="Marca cuando hayas contrastado el contrato fisico contra la factura",
                default=False,
            ),
        },
        disabled=disabled_cols,
        hide_index=True,
        use_container_width=True,
        key="_fin_editor",
    )

    # Detectar cambios en la columna 'Revisada' y persistir
    if not edited_view["Revisada"].equals(view["Revisada"]):
        for i in range(len(view)):
            orig = bool(view.iloc[i]["Revisada"])
            new = bool(edited_view.iloc[i]["Revisada"])
            if orig == new:
                continue
            invoice_id = int(edited_view.iloc[i]["ID"])
            if new:
                execute_write("""
                    UPDATE operational.invoices
                    SET revisada     = TRUE,
                        revisada_at  = NOW(),
                        revisada_por = :user
                    WHERE invoice_id = :id
                """, {"id": invoice_id, "user": username})
            else:
                execute_write("""
                    UPDATE operational.invoices
                    SET revisada     = FALSE,
                        revisada_at  = NULL,
                        revisada_por = NULL
                    WHERE invoice_id = :id
                """, {"id": invoice_id})
        load_query.clear()
        st.rerun()

    n_revisadas = int(view["Revisada"].sum())
    st.caption(
        f"Mostrando {len(view)} facturas finalizadas "
        f"(entrega entre {hist_desde} y {hist_hasta}) — "
        f"{n_revisadas} revisada(s), {len(view) - n_revisadas} pendiente(s) de revision. "
        f"'Δ TRM' positivo = el asesor uso una TRM mas alta que la oficial; "
        f"negativo = uso una mas baja."
    )
    # Export: dropear dup_all_ids (lista de Postgres, openpyxl no soporta listas).
    # La columna formateada 'duplicados' (string "Dup con #X, #Y") sigue presente.
    df_fin_export = df_fin.drop(columns=["dup_all_ids"], errors="ignore").copy()
    xlsx_download_button(
        df_fin_export,
        file_name=f"facturas_finalizadas_{dt.date.today()}",
        sheet_name="Finalizadas",
        key="xlsx_facturas_finalizadas",
    )

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

        # -----------------------------------------------------------------
        # ADMIN ONLY: Eliminar permanentemente una factura por ID
        # -----------------------------------------------------------------
        # Para borrar duplicados o facturas creadas por error (typos, tests).
        # Accion irreversible — requiere confirmacion explicita.
        st.markdown("##### Eliminar factura (admin)")
        st.caption(
            "Elimina PERMANENTEMENTE una factura por ID. No se puede deshacer. "
            "Usar para duplicados o facturas creadas por error."
        )
        del_cols = st.columns([2, 2, 1])
        delete_id_str = del_cols[0].text_input(
            "ID de factura a eliminar",
            key="_admin_delete_id",
            placeholder="ej. 116",
        )
        delete_confirm = del_cols[1].checkbox(
            "Confirmo que quiero eliminarla (irreversible)",
            key="_admin_delete_confirm",
        )
        if del_cols[2].button("Eliminar", key="_admin_delete_btn", type="primary"):
            try:
                delete_id = int(delete_id_str.strip())
            except (ValueError, AttributeError):
                st.error("Ingresa un ID valido (numero entero).")
            else:
                if not delete_confirm:
                    st.error("Marca la casilla de confirmacion antes de eliminar.")
                else:
                    check = load_query(
                        "SELECT invoice_id, rntl_mvnr, sede_nombre, monto_total, "
                        "       finalizada "
                        "FROM operational.invoices WHERE invoice_id = :id",
                        {"id": delete_id},
                    )
                    if check.empty:
                        st.error(f"No existe factura con ID {delete_id}.")
                    else:
                        row = check.iloc[0]
                        execute_write(
                            "DELETE FROM operational.invoices WHERE invoice_id = :id",
                            {"id": delete_id},
                        )
                        status_tag = "cerrada" if bool(row["finalizada"]) else "abierta"
                        st.success(
                            f"Factura #{delete_id} ELIMINADA "
                            f"(contrato {int(row['rntl_mvnr'])}, "
                            f"sede {row['sede_nombre']}, "
                            f"monto {fmt_money(float(row['monto_total']), 'COP')}, "
                            f"estaba {status_tag})."
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
          -- Excluir contratos con revenue 0 (cortesias, status-match con placa
          -- real, asesor 7784272, etc.). Si no hay nada que cobrar no hay factura.
          AND COALESCE(r.total_con_iva_usd, 0) > 0
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
