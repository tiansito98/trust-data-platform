"""
Documentos (piloto del reemplazo de Odoo Documents) — solo trust_admin.

Carpetas + subir / abrir / descargar archivos en Supabase Storage (bucket privado
'documentos') y firmar PDFs con el mouse. Indice en operational.doc_carpetas y
operational.documentos; logica en components/documentos.py y components/storage.py.

Abrir = URL firmada de 5 minutos (la llave de Storage nunca llega al navegador).
Firmar = copia NUEVA del PDF con la firma vectorial estampada; el original queda igual.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from components.common import inject_styles, render_header, section, kpi, fmt_int
from components.auth import require_auth, require_page, logout_button, get_current_user
from components import storage as S

st.set_page_config(page_title="TRUST - Documentos", layout="wide")
require_auth()
require_page("13_Documentos")
inject_styles()
logout_button()

_u = get_current_user()
if not _u or _u.get("username") != "trust_admin":
    render_header("Documentos")
    st.warning("Por ahora solo el perfil **trust_admin** puede ver esta página (piloto).")
    st.stop()
USUARIO = _u["username"]

render_header("Documentos")

if not S.configurado():
    st.error(
        "Falta configurar Supabase Storage. Agrega en los secrets (y en `.env` para local):\n\n"
        "```\nSUPABASE_URL = \"https://<ref>.supabase.co\"\n"
        "SUPABASE_SERVICE_ROLE_KEY = \"...\"\n```\n\n"
        "La llave sale de Supabase → Project Settings → API Keys (service_role o secret key)."
    )
    st.stop()

from components import documentos as D  # noqa: E402  (importa el componente de firma)

try:
    D.ensure_tables()
except Exception as e:  # noqa: BLE001
    st.error(f"No se pudo preparar Storage / tablas: {e}")
    st.stop()


def _tam(n) -> str:
    n = float(n or 0)
    if n < 1024:
        return f"{n:.0f} B"
    for u in ("KB", "MB", "GB"):
        n /= 1024
        if n < 1024 or u == "GB":
            return f"{n:.1f} {u}".replace(".", ",")


# =============================================================================
# Carpetas
# =============================================================================
df_c = D.carpetas()
rutas = D.rutas_carpetas(df_c) if not df_c.empty else {}

c_sel, c_new = st.columns([3, 2])
with c_new:
    with st.expander("Nueva carpeta", expanded=not rutas):
        with st.form("doc_new_folder", clear_on_submit=True):
            nombre = st.text_input("Nombre")
            padre = st.selectbox("Dentro de", [None] + list(rutas),
                                 format_func=lambda c: "(raíz)" if c is None else rutas[c],
                                 index=([None] + list(rutas)).index(st.session_state.get("doc_carpeta"))
                                 if st.session_state.get("doc_carpeta") in rutas else 0)
            if st.form_submit_button("Crear"):
                if not nombre.strip():
                    st.error("Ponle un nombre.")
                else:
                    try:
                        D.crear_carpeta(nombre, padre, USUARIO)
                        st.success(f"Carpeta '{nombre.strip()}' creada.")
                        st.rerun()
                    except Exception as e:  # noqa: BLE001
                        st.error("Ya existe una carpeta con ese nombre ahí." if "unique" in str(e).lower()
                                 else f"No se pudo crear: {e}")

if not rutas:
    st.info("Todavía no hay carpetas. Crea la primera a la derecha.")
    st.stop()

with c_sel:
    carpeta = st.selectbox("Carpeta", list(rutas), format_func=lambda c: rutas[c], key="doc_carpeta")

docs = D.documentos(carpeta)
k1, k2, k3 = st.columns(3)
kpi(k1, "Archivos en la carpeta", fmt_int(len(docs)))
kpi(k2, "Tamaño", _tam(docs["tamano_bytes"].sum() if not docs.empty else 0))
kpi(k3, "Firmados", fmt_int(int(docs["firmado_de"].notna().sum()) if not docs.empty else 0))

tab_ver, tab_subir, tab_firmar = st.tabs(["Archivos", "Subir", "Firmar PDF"])

# =============================================================================
# Archivos: listar / abrir / descargar / eliminar
# =============================================================================
with tab_ver:
    if docs.empty:
        st.info("La carpeta está vacía. Sube archivos en la pestaña **Subir**.")
    else:
        view = pd.DataFrame({
            "Nombre": docs["nombre"],
            "Tipo": docs["mime_type"].fillna(""),
            "Tamaño": docs["tamano_bytes"].map(_tam),
            "Subido por": docs["subido_por"],
            "Subido": pd.to_datetime(docs["subido_at"], utc=True)
                        .dt.tz_convert("America/Bogota").dt.strftime("%d/%m/%Y %H:%M"),
            "Firmado": docs["firmado_de"].notna().map({True: "Sí", False: ""}),
        })
        st.dataframe(view, use_container_width=True, hide_index=True)

        opciones = dict(zip(docs["documento_id"].astype(int), docs["nombre"]))
        _pend = st.session_state.pop("doc_abrir_pendiente", None)
        if _pend in opciones:
            st.session_state["doc_abrir"] = _pend
        doc_id = st.selectbox("Abrir archivo", list(opciones), format_func=opciones.get, key="doc_abrir")
        fila = docs[docs["documento_id"] == doc_id].iloc[0]
        try:
            url = S.signed_url(fila["storage_path"], 300)
            url_dl = S.signed_url(fila["storage_path"], 300, descargar_como=fila["nombre"])
        except Exception as e:  # noqa: BLE001
            st.error(f"No se pudo generar el enlace: {e}")
            url = url_dl = None

        if url:
            b1, b2, b3 = st.columns([1, 1, 3])
            b1.link_button("Abrir en pestaña nueva", url, use_container_width=True)
            b2.link_button("Descargar", url_dl, use_container_width=True)
            b3.caption("Los enlaces vencen en 5 minutos; recarga la página para uno nuevo.")
            mime = (fila["mime_type"] or "").lower()
            if mime == "application/pdf":
                components.iframe(url, height=750, scrolling=True)
            elif mime.startswith("image/"):
                st.image(url)
            elif mime.startswith("text/") or mime in ("application/json", "text/csv"):
                try:
                    st.code(S.download(fila["storage_path"])[:200_000].decode("utf-8", "replace"))
                except Exception as e:  # noqa: BLE001
                    st.error(str(e))
            else:
                st.caption("Vista previa solo para PDF, imágenes y texto. Usa *Abrir* o *Descargar*.")

        with st.expander("Eliminar este archivo"):
            seguro = st.checkbox(f"Sí, eliminar '{fila['nombre']}'", key=f"doc_del_ok_{doc_id}")
            if st.button("Eliminar", disabled=not seguro, key=f"doc_del_{doc_id}"):
                D.eliminar(doc_id, USUARIO)
                st.success("Eliminado.")
                st.rerun()

# =============================================================================
# Subir
# =============================================================================
with tab_subir:
    st.caption(f"Se suben a **{rutas[carpeta]}**. Máximo 50 MB por archivo.")
    nonce = st.session_state.setdefault("doc_up_nonce", 0)
    with st.form(f"doc_upload_{nonce}"):
        files = st.file_uploader("Archivos", accept_multiple_files=True, key=f"doc_files_{nonce}")
        desc = st.text_input("Descripción (opcional)")
        ok = st.form_submit_button("Subir")
    if ok:
        if not files:
            st.error("Elige al menos un archivo.")
        else:
            subidos, errores = 0, []
            barra = st.progress(0.0)
            for i, f in enumerate(files, 1):
                data = f.getvalue()
                if len(data) > 50 * 1024 * 1024:
                    errores.append(f"{f.name}: pesa más de 50 MB")
                    continue
                try:
                    D.subir(carpeta, f.name, data, f.type or "application/octet-stream", USUARIO, desc)
                    subidos += 1
                except Exception as e:  # noqa: BLE001
                    errores.append(f"{f.name}: {e}")
                barra.progress(i / len(files))
            if subidos:
                st.success(f"{subidos} archivo(s) subido(s).")
            for e in errores:
                st.error(e)
            if subidos and not errores:
                st.session_state["doc_up_nonce"] = nonce + 1
                st.rerun()

# =============================================================================
# Firmar PDF
# =============================================================================
with tab_firmar:
    pdfs = docs[docs["mime_type"].fillna("").str.lower().eq("application/pdf")] if not docs.empty else docs
    if pdfs.empty:
        st.info("No hay PDFs en esta carpeta.")
    else:
        op_pdf = dict(zip(pdfs["documento_id"].astype(int), pdfs["nombre"]))
        pdf_id = st.selectbox("PDF a firmar", list(op_pdf), format_func=op_pdf.get, key="doc_firmar_pdf")
        fila = pdfs[pdfs["documento_id"] == pdf_id].iloc[0]

        @st.cache_data(show_spinner=False, max_entries=4)
        def _bytes(path: str) -> bytes:
            return S.download(path)

        try:
            data = _bytes(fila["storage_path"])
            paginas = D.info_pdf(data)
        except Exception as e:  # noqa: BLE001
            st.error(f"No se pudo leer el PDF: {e}")
            st.stop()

        section("1. Dibuja la firma con el mouse (o el dedo en el celular)")
        firma = D.panel_firma("doc_firma")
        if firma and firma.get("png"):
            st.image(firma["png"], caption="Firma capturada", width=240)

        section("2. Dónde va")
        p1, p2, p3, p4 = st.columns(4)
        pagina = p1.number_input("Página", 1, len(paginas), len(paginas), key="doc_firma_pag") - 1
        pos = p2.selectbox("Posición", ["Abajo a la derecha", "Abajo al centro",
                                        "Abajo a la izquierda", "Personalizada"], key="doc_firma_pos")
        ancho = p3.slider("Ancho de la firma (% de la hoja)", 10, 60, 28, key="doc_firma_ancho")
        leyenda_on = p4.checkbox("Agregar 'Firmado por ... fecha'", True, key="doc_firma_ley")
        presets = {"Abajo a la derecha": (100 - ancho - 8, 8), "Abajo al centro": ((100 - ancho) / 2, 8),
                   "Abajo a la izquierda": (8, 8)}
        if pos == "Personalizada":
            q1, q2 = st.columns(2)
            x_pct = q1.slider("Desde la izquierda (%)", 0, 95, 60, key="doc_firma_x")
            y_pct = q2.slider("Desde abajo (%)", 0, 95, 8, key="doc_firma_y")
        else:
            x_pct, y_pct = presets[pos]
        ahora = pd.Timestamp.now(tz="America/Bogota").strftime("%d/%m/%Y %H:%M")
        leyenda = f"Firmado por {USUARIO} - {ahora}" if leyenda_on else ""

        section("3. Revisar y guardar")
        if not firma:
            st.info("Dibuja la firma y presiona **Usar esta firma**.")
        else:
            try:
                firmado = D.estampar_firma(data, firma, int(pagina), x_pct, y_pct, ancho, leyenda)
            except Exception as e:  # noqa: BLE001
                st.error(f"No se pudo estampar la firma: {e}")
                firmado = None
            if firmado:
                r1, r2 = st.columns(2)
                r1.download_button("Descargar para revisar", firmado, file_name=D.nombre_firmado(fila["nombre"]),
                                   mime="application/pdf", use_container_width=True)
                if r2.button("Guardar copia firmada en la carpeta", type="primary", use_container_width=True):
                    try:
                        nuevo = D.subir(carpeta, D.nombre_firmado(fila["nombre"]), firmado, "application/pdf",
                                        USUARIO, f"Firma de '{fila['nombre']}'", firmado_de=int(pdf_id))
                        D.limpiar_firma("doc_firma")
                        st.session_state["doc_abrir_pendiente"] = int(nuevo)
                        st.success("Guardada. Está en la pestaña **Archivos**, seleccionada.")
                        st.rerun()
                    except Exception as e:  # noqa: BLE001
                        st.error(f"No se pudo guardar: {e}")
            st.caption("El original no se modifica: se guarda una copia nueva con la firma. "
                       "Es una firma manuscrita digitalizada (imagen de la firma), no una firma "
                       "digital certificada.")
