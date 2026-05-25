"""
Disponibilidad de Flota - grilla mensual de estado de vehiculos.

Muestra una grilla (vehiculo x dia) coloreada por estado. Combina datos
automaticos de Sixt (rentals/reservas) con estados manuales registrados
por el asesor del counter (taller, PYP, transito, lavado, bloqueado).

Los estados manuales siempre tienen prioridad sobre los automaticos.

Escribe/borra de operational.op_disponibilidad_manual.
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
    render_trm_today_sidebar,
)


st.set_page_config(page_title="TRUST - Disponibilidad de Flota", layout="wide")
require_auth()
require_page("7_Disponibilidad_Flota")
inject_styles()
render_trm_today_sidebar()
logout_button()
render_header("Disponibilidad de Flota")


# =============================================================================
# Estado config
# =============================================================================

ESTADO_CONFIG = {
    "DISPONIBLE":  {"color": "#e8f5e9", "text_color": "#333", "label": ""},
    "RENTADO":     {"color": "#ffcdd2", "text_color": "#333", "label": ""},
    "RESERVADO":   {"color": "#fff3e0", "text_color": "#333", "label": "RSV"},
    "PYP":         {"color": "#fff9c4", "text_color": "#333", "label": "PYP"},
    "PYP_EXENTO":  {"color": "#c8e6c9", "text_color": "#333", "label": "EX"},
    "TALLER":      {"color": "#bbdefb", "text_color": "#333", "label": "TALL"},
    "TRANSITO":    {"color": "#e0e0e0", "text_color": "#333", "label": "TRAN"},
    "LAVADO":      {"color": "#b2ebf2", "text_color": "#333", "label": "LAV"},
    "BLOQUEADO":   {"color": "#424242", "text_color": "#fff", "label": "BLOQ"},
}

MANUAL_ESTADOS = ["PYP", "PYP_EXENTO", "TALLER", "TRANSITO", "LAVADO", "BLOQUEADO"]


# =============================================================================
# Sede selector
# =============================================================================

try:
    sedes = load_query(
        "SELECT DISTINCT sede_codigo, sede_nombre "
        "FROM vw_disponibilidad_vehiculo_dia "
        "WHERE sede_nombre IS NOT NULL "
        "ORDER BY sede_nombre"
    )
except Exception:
    sedes = pd.DataFrame()

if sedes.empty:
    st.warning("No hay datos de disponibilidad. Ejecute el pipeline silver primero.")
    st.stop()

sede_map = dict(zip(sedes["sede_nombre"], sedes["sede_codigo"].astype(int)))
sede_map_inv = {v: k for k, v in sede_map.items()}

user_branches = get_user_branches()

if is_admin() or "*" in user_branches:
    sede_nombre = st.sidebar.selectbox("Sede", options=list(sede_map.keys()))
else:
    locked = user_branches[0] if user_branches else ""
    st.sidebar.text_input("Sede (fija)", value=locked, disabled=True)
    sede_nombre = locked

if sede_nombre not in sede_map:
    st.error(f"Sede '{sede_nombre}' no encontrada en los datos de disponibilidad.")
    st.stop()

sede_codigo = sede_map[sede_nombre]


# =============================================================================
# Month selector
# =============================================================================

today = dt.date.today()
month_options = []
for delta in [-1, 0, 1]:
    m = today.month + delta
    y = today.year
    if m < 1:
        m += 12
        y -= 1
    elif m > 12:
        m -= 12
        y += 1
    month_options.append(dt.date(y, m, 1))

month_labels = [d.strftime("%B %Y") for d in month_options]
default_idx = 1
selected_label = st.sidebar.selectbox("Mes", options=month_labels, index=default_idx)
selected_month = month_options[month_labels.index(selected_label)]


# =============================================================================
# Load grid data
# =============================================================================

import calendar
last_day = calendar.monthrange(selected_month.year, selected_month.month)[1]
fecha_desde = selected_month
fecha_hasta = dt.date(selected_month.year, selected_month.month, last_day)

df = load_query("""
    SELECT vhcl_int_num, placa, vehiculo, acriss, sede_codigo, sede_nombre,
           fecha, estado, origen, numero_contrato, numero_reserva,
           asesor_codigo, nota, created_by
    FROM vw_disponibilidad_vehiculo_dia
    WHERE sede_codigo = :sede
      AND fecha BETWEEN :desde AND :hasta
    ORDER BY vehiculo, placa, fecha
""", {"sede": sede_codigo, "desde": fecha_desde, "hasta": fecha_hasta})

if df.empty:
    st.info("No hay vehiculos para esta sede y mes.")
    st.stop()


# =============================================================================
# Color legend
# =============================================================================

legend_items = []
for estado, cfg in ESTADO_CONFIG.items():
    legend_items.append(
        f'<span style="display:inline-block;width:14px;height:14px;'
        f'background:{cfg["color"]};border:1px solid #ccc;'
        f'vertical-align:middle;margin-right:3px;border-radius:2px;"></span>'
        f'<span style="vertical-align:middle;margin-right:14px;font-size:0.82rem;">'
        f'{estado.replace("_", " ").title()}</span>'
    )
st.markdown(
    '<div style="margin-bottom:12px;">' + " ".join(legend_items) + '</div>',
    unsafe_allow_html=True,
)


# =============================================================================
# Build grid
# =============================================================================

df["dia"] = pd.to_datetime(df["fecha"]).dt.day
df["vehiculo_label"] = df["vehiculo"] + " | " + df["placa"] + " | " + df["acriss"]


def _cell_text(row):
    estado = row["estado"]
    if estado == "DISPONIBLE":
        return ""
    if estado == "RENTADO":
        if pd.notna(row["asesor_codigo"]) and str(row["asesor_codigo"]).strip():
            return str(row["asesor_codigo"])[:6]
        if pd.notna(row["numero_contrato"]):
            return str(int(row["numero_contrato"]))[-6:]
        return "RENT"
    cfg = ESTADO_CONFIG.get(estado)
    if cfg:
        return cfg["label"]
    return estado[:4]


df["cell_text"] = df.apply(_cell_text, axis=1)

pivot_estado = df.pivot_table(
    index="vehiculo_label", columns="dia", values="estado", aggfunc="first"
)
pivot_texto = df.pivot_table(
    index="vehiculo_label", columns="dia", values="cell_text", aggfunc="first"
)

pivot_estado = pivot_estado.reindex(columns=range(1, last_day + 1))
pivot_texto = pivot_texto.reindex(columns=range(1, last_day + 1)).fillna("")


def _apply_colors(col):
    styles = []
    for i in range(len(col)):
        estado = pivot_estado.iloc[i].get(col.name, "DISPONIBLE")
        if pd.isna(estado):
            estado = "DISPONIBLE"
        cfg = ESTADO_CONFIG.get(estado, ESTADO_CONFIG["DISPONIBLE"])
        styles.append(
            f"background-color: {cfg['color']}; color: {cfg['text_color']}; "
            f"text-align: center; font-size: 10px; padding: 2px 1px;"
        )
    return styles


styled = pivot_texto.style.apply(_apply_colors, axis=0)
styled = styled.set_properties(**{"min-width": "28px", "max-width": "40px"})
styled = styled.set_table_styles([
    {"selector": "th", "props": [("font-size", "11px"), ("text-align", "center"),
                                  ("padding", "4px 2px")]},
    {"selector": "td", "props": [("padding", "3px 1px")]},
    {"selector": "th.row_heading", "props": [("font-size", "10px"),
                                              ("text-align", "left"),
                                              ("white-space", "nowrap")]},
])

section(f"Grilla - {sede_nombre} - {selected_label}")
st.dataframe(styled, use_container_width=True, height=600)
st.caption(f"{pivot_estado.shape[0]} vehiculos x {last_day} dias")


# =============================================================================
# Form: register manual state
# =============================================================================

st.markdown("---")
section("Registrar estado manual")

vehiculos_sede = load_query("""
    SELECT DISTINCT vhcl_int_num, placa, vehiculo, acriss
    FROM vw_disponibilidad_vehiculo_dia
    WHERE sede_codigo = :sede
    ORDER BY vehiculo, placa
""", {"sede": sede_codigo})

if vehiculos_sede.empty:
    st.info("No hay vehiculos disponibles para esta sede.")
else:
    vehiculos_sede["label"] = (
        vehiculos_sede["vehiculo"] + " | "
        + vehiculos_sede["placa"] + " | "
        + vehiculos_sede["acriss"]
    )
    veh_map = dict(zip(
        vehiculos_sede["label"],
        vehiculos_sede[["vhcl_int_num", "placa"]].apply(tuple, axis=1),
    ))

    with st.form("manual_state_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        selected_veh = c1.selectbox("Vehiculo", options=list(veh_map.keys()))
        estado_sel = c2.selectbox("Estado", options=MANUAL_ESTADOS)

        c3, c4 = st.columns(2)
        form_desde = c3.date_input("Desde", value=today)
        form_hasta = c4.date_input("Hasta", value=today)

        c5, c6 = st.columns(2)
        nota = c5.text_input("Nota (opcional)", placeholder="Motivo o detalle")
        asesor = c6.text_input("Asesor (opcional)", placeholder="Codigo del asesor")

        submitted = st.form_submit_button("Guardar")

    if submitted:
        if form_hasta < form_desde:
            st.error("La fecha 'Hasta' no puede ser anterior a 'Desde'.")
        elif selected_veh not in veh_map:
            st.error("Seleccione un vehiculo valido.")
        else:
            vhcl_int_num, placa = veh_map[selected_veh]
            current_user = get_current_user()
            username = current_user["username"] if current_user else "unknown"
            days_saved = 0
            try:
                d = form_desde
                while d <= form_hasta:
                    execute_write("""
                        INSERT INTO operational.op_disponibilidad_manual
                            (vhcl_int_num, placa, fecha, estado, nota,
                             asesor_codigo, sede_codigo, created_by)
                        VALUES (:vhcl, :placa, :fecha, :estado, :nota,
                                :asesor, :sede, :user_name)
                        ON CONFLICT (vhcl_int_num, fecha) DO UPDATE SET
                            estado = EXCLUDED.estado,
                            nota = EXCLUDED.nota,
                            asesor_codigo = EXCLUDED.asesor_codigo,
                            created_by = EXCLUDED.created_by,
                            created_at = NOW()
                    """, {
                        "vhcl": int(vhcl_int_num),
                        "placa": str(placa),
                        "fecha": d,
                        "estado": estado_sel,
                        "nota": nota.strip() or None,
                        "asesor": asesor.strip() or None,
                        "sede": sede_codigo,
                        "user_name": username,
                    })
                    days_saved += 1
                    d += dt.timedelta(days=1)

                st.success(
                    f"Estado '{estado_sel}' registrado para {selected_veh} "
                    f"({days_saved} dia{'s' if days_saved != 1 else ''})."
                )
                load_query.clear()
            except Exception as e:
                st.error(f"Error guardando: {e}")


# =============================================================================
# Recent entries + delete
# =============================================================================

st.markdown("---")
section("Entradas manuales recientes")

recent = load_query("""
    SELECT id, placa, fecha, estado, nota, asesor_codigo, created_by, created_at
    FROM operational.op_disponibilidad_manual
    WHERE sede_codigo = :sede
    ORDER BY created_at DESC
    LIMIT 20
""", {"sede": sede_codigo})

if recent.empty:
    st.info("No hay entradas manuales para esta sede.")
else:
    st.dataframe(recent, use_container_width=True, hide_index=True)

    selected_ids = st.multiselect(
        "Seleccionar entradas para borrar (por ID)",
        options=recent["id"].tolist(),
        format_func=lambda x: (
            f"ID {x} - {recent.loc[recent['id']==x, 'placa'].iloc[0]} "
            f"- {recent.loc[recent['id']==x, 'fecha'].iloc[0]} "
            f"- {recent.loc[recent['id']==x, 'estado'].iloc[0]}"
        ),
    )

    if selected_ids and st.button("Borrar seleccionadas"):
        try:
            for sid in selected_ids:
                execute_write(
                    "DELETE FROM operational.op_disponibilidad_manual WHERE id = :id",
                    {"id": int(sid)},
                )
            st.success(f"{len(selected_ids)} entrada(s) eliminada(s).")
            load_query.clear()
        except Exception as e:
            st.error(f"Error borrando: {e}")
