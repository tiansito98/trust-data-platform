"""
Documentos (piloto del reemplazo de Odoo Documents) — solo trust_admin.

Carpetas + subir / ver / descargar archivos en Supabase Storage (bucket privado
'documentos') y firmar PDFs con el mouse. Indice en operational.doc_carpetas y
operational.documentos; logica en components/documentos.py y components/storage.py.

- Cada documento se puede atar a un CONTRATO; la(s) placa(s) salen de silver, asi que
  se puede buscar todo lo anexado a un carro por placa o por contrato.
- Vista previa de PDF = paginas rasterizadas en el servidor (el visor del navegador
  no carga dentro de Streamlit).
- Firmar = vista previa de la pagina firmada -> guardar una COPIA en la carpeta
  'Documentos firmados'. La leyenda del PDF solo lleva la fecha; QUIEN firmo queda
  en la base (firmado_por / firmado_at).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import streamlit as st

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
        "La llave sale de Supabase → Project Settings → API Keys (secret key)."
    )
    st.stop()

from components import documentos as D  # noqa: E402  (importa el componente de firma)

# Streamlit Cloud puede servir el modulo viejo tras un push (ver CLAUDE.md): recargarlo.
D_API_REQUERIDA = 3
if getattr(D, "API_VERSION", 0) < D_API_REQUERIDA:
    import importlib
    D = importlib.reload(D)

try:
    D.ensure_tables()
except Exception as e:  # noqa: BLE001
    st.error(f"No se pudo preparar Storage / tablas: {e}")
    st.stop()


# =============================================================================
# Helpers de la pagina
# =============================================================================
def _tam(n) -> str:
    n = float(n or 0)
    if n < 1024:
        return f"{n:.0f} B"
    for u in ("KB", "MB", "GB"):
        n /= 1024
        if n < 1024 or u == "GB":
            return f"{n:.1f} {u}".replace(".", ",")


def _fecha(v) -> str:
    if v is None or pd.isna(v):
        return ""
    return pd.Timestamp(v).tz_convert("America/Bogota").strftime("%d/%m/%Y %H:%M") \
        if pd.Timestamp(v).tzinfo else pd.Timestamp(v).strftime("%d/%m/%Y %H:%M")


def _placas(v) -> str:
    return ", ".join(v) if isinstance(v, (list, tuple)) and len(v) else ""


@st.cache_data(show_spinner=False, max_entries=8)
def _bytes(path: str) -> bytes:
    # storage_path es unico e inmutable (uuid), asi que cachear por path es seguro
    return S.download(path)


@st.cache_data(show_spinner=False, max_entries=24)
def _png(path: str, pagina: int) -> bytes:
    return D.render_pagina(_bytes(path), pagina)


@st.cache_data(show_spinner=False, max_entries=8)
def _npag(path: str) -> int:
    return D.n_paginas(_bytes(path))


def input_contrato(label: str, key: str, default=None):
    """Campo de contrato. Devuelve (ok, dict|None). ok=False si lo escrito es invalido."""
    txt = st.text_input(label, value="" if default in (None, "") or pd.isna(default) else str(int(default)),
                        key=key, placeholder="ej. 9524178852 (opcional)")
    t = (txt or "").strip()
    if not t:
        return True, None
    if not t.isdigit():
        st.error("El contrato son solo números.")
        return False, None
    info = D.info_contrato(int(t))
    if info is None:
        st.warning("Ese contrato no está en la base todavía (el pipeline lo trae en la madrugada). "
                   "Se guarda el número; la placa se completa al volver a vincularlo.")
        return True, {"contrato": int(t), "placas": [], "sede": None}
    st.caption(f"Placa(s): **{_placas(info['placas']) or '-'}** · {info['sede'] or ''} · "
               f"entrega {info['entrega']}")
    return True, info


def visor(fila, key: str) -> None:
    """Abrir / descargar / vista previa de un documento + su contrato."""
    try:
        url = S.signed_url(fila["storage_path"], 300)
        url_dl = S.signed_url(fila["storage_path"], 300, descargar_como=fila["nombre"])
    except Exception as e:  # noqa: BLE001
        st.error(f"No se pudo generar el enlace: {e}")
        return
    b1, b2, b3 = st.columns([1, 1, 3])
    b1.link_button("Abrir en pestaña nueva", url, use_container_width=True)
    b2.link_button("Descargar", url_dl, use_container_width=True)
    info = []
    if pd.notna(fila.get("contrato")):
        info.append(f"Contrato **{int(fila['contrato'])}** · placa(s) **{_placas(fila.get('placas')) or '-'}**")
    if pd.notna(fila.get("firmado_de")):
        info.append(f"Firmado por **{fila['firmado_por']}** el {_fecha(fila['firmado_at'])}")
    b3.caption(" · ".join(info) if info else "Sin contrato vinculado.")

    mime = (fila["mime_type"] or "").lower()
    if mime == "application/pdf":
        try:
            n = _npag(fila["storage_path"])
            pg = 1
            if n > 1:
                pg = st.number_input(f"Página (de {n})", 1, n, 1, key=f"{key}_pg")
            st.image(_png(fila["storage_path"], int(pg) - 1), use_container_width=True)
        except Exception as e:  # noqa: BLE001
            st.error(f"No se pudo mostrar el PDF: {e}")
    elif mime.startswith("image/"):
        st.image(url)
    elif mime.startswith("text/") or mime in ("application/json",):
        try:
            st.code(_bytes(fila["storage_path"])[:200_000].decode("utf-8", "replace"))
        except Exception as e:  # noqa: BLE001
            st.error(str(e))
    else:
        st.caption("Vista previa solo para PDF, imágenes y texto. Usa *Abrir* o *Descargar*.")


def tabla(docs: pd.DataFrame, rutas: dict | None = None) -> None:
    view = pd.DataFrame({
        "Nombre": docs["nombre"],
        **({"Carpeta": docs["carpeta_id"].map(lambda c: rutas.get(int(c), ""))} if rutas else {}),
        "Contrato": docs["contrato"].map(lambda v: "" if pd.isna(v) else str(int(v))),
        "Placa(s)": docs["placas"].map(_placas),
        "Tamaño": docs["tamano_bytes"].map(_tam),
        "Subido por": docs["subido_por"],
        "Subido": docs["subido_at"].map(_fecha),
        "Firmado por": docs["firmado_por"].fillna(""),
    })
    st.dataframe(view, use_container_width=True, hide_index=True)


# =============================================================================
# Buscar por contrato o placa (en todas las carpetas)
# =============================================================================
df_c = D.carpetas()
rutas = D.rutas_carpetas(df_c) if not df_c.empty else {}

q = st.text_input("Buscar por contrato o placa", key="doc_buscar",
                  placeholder="ej. 9524178852 o QQT746")
if q.strip():
    res = D.buscar(q)
    if res.empty:
        st.info("No hay documentos para ese contrato o placa.")
    else:
        st.caption(f"{len(res)} documento(s).")
        tabla(res, rutas)
        op = dict(zip(res["documento_id"].astype(int), res["nombre"]))
        did = st.selectbox("Ver", list(op), format_func=op.get, key="doc_buscar_sel")
        visor(res[res["documento_id"] == did].iloc[0], f"b{did}")
    st.divider()

# =============================================================================
# Carpetas
# =============================================================================
_pend_c = st.session_state.pop("doc_carpeta_pendiente", None)
if _pend_c in rutas:
    st.session_state["doc_carpeta"] = _pend_c

c_sel, c_new = st.columns([3, 2])
with c_new:
    with st.expander("Nueva carpeta", expanded=not rutas):
        with st.form("doc_new_folder", clear_on_submit=True):
            nombre = st.text_input("Nombre")
            opciones_padre = [None] + list(rutas)
            actual = st.session_state.get("doc_carpeta")
            padre = st.selectbox("Dentro de", opciones_padre,
                                 format_func=lambda c: "(raíz)" if c is None else rutas[c],
                                 index=opciones_padre.index(actual) if actual in rutas else 0)
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
kpi(k3, "Con contrato", fmt_int(int(docs["contrato"].notna().sum()) if not docs.empty else 0))

tab_ver, tab_subir, tab_firmar = st.tabs(["Archivos", "Subir", "Firmar PDF"])

# =============================================================================
# Archivos
# =============================================================================
with tab_ver:
    if docs.empty:
        st.info("La carpeta está vacía. Sube archivos en la pestaña **Subir**.")
    else:
        tabla(docs)
        opciones = dict(zip(docs["documento_id"].astype(int), docs["nombre"]))
        _pend = st.session_state.pop("doc_abrir_pendiente", None)
        if _pend in opciones:
            st.session_state["doc_abrir"] = _pend
        doc_id = st.selectbox("Ver archivo", list(opciones), format_func=opciones.get, key="doc_abrir")
        fila = docs[docs["documento_id"] == doc_id].iloc[0]
        visor(fila, f"v{doc_id}")

        with st.expander("Vincular a un contrato"):
            ok_c, ct = input_contrato("Contrato", f"doc_vinc_{doc_id}", fila.get("contrato"))
            if st.button("Guardar vínculo", key=f"doc_vinc_btn_{doc_id}", disabled=not ok_c):
                D.vincular_contrato(doc_id, ct)
                st.success("Vínculo guardado." if ct else "Contrato quitado.")
                st.rerun()

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
    ok_c, ct_up = input_contrato("Contrato (opcional; aplica a todos los archivos de esta subida)",
                                 f"doc_up_ct_{nonce}")
    with st.form(f"doc_upload_{nonce}"):
        files = st.file_uploader("Archivos", accept_multiple_files=True, key=f"doc_files_{nonce}")
        desc = st.text_input("Descripción (opcional)")
        ok = st.form_submit_button("Subir", disabled=not ok_c)
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
                    D.subir(carpeta, f.name, data, f.type or "application/octet-stream", USUARIO,
                            desc, contrato=ct_up)
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
        try:
            data = _bytes(fila["storage_path"])
            paginas = D.info_pdf(data)
        except Exception as e:  # noqa: BLE001
            st.error(f"No se pudo leer el PDF: {e}")
            st.stop()

        section("1. Contrato")
        ok_cf, ct_f = input_contrato("Contrato al que pertenece el documento firmado",
                                     f"doc_firma_ct_{pdf_id}", fila.get("contrato"))

        section("2. Dibuja la firma con el mouse (o el dedo en el celular)")
        firma = D.panel_firma("doc_firma")

        section("3. Dónde va")
        p1, p2, p3, p4 = st.columns(4)
        pagina = p1.number_input(f"Página (de {len(paginas)})", 1, len(paginas), len(paginas),
                                 key=f"doc_firma_pag_{pdf_id}") - 1
        pos = p2.selectbox("Posición", ["Abajo a la derecha", "Abajo al centro",
                                        "Abajo a la izquierda", "Personalizada"], key="doc_firma_pos")
        ancho = p3.slider("Ancho de la firma (% de la hoja)", 10, 60, 28, key="doc_firma_ancho")
        leyenda_on = p4.checkbox("Agregar la fecha de la firma", True, key="doc_firma_ley")
        presets = {"Abajo a la derecha": (100 - ancho - 8, 8), "Abajo al centro": ((100 - ancho) / 2, 8),
                   "Abajo a la izquierda": (8, 8)}
        if pos == "Personalizada":
            q1, q2 = st.columns(2)
            x_pct = q1.slider("Desde la izquierda (%)", 0, 95, 60, key="doc_firma_x")
            y_pct = q2.slider("Desde abajo (%)", 0, 95, 8, key="doc_firma_y")
        else:
            x_pct, y_pct = presets[pos]
        ahora = pd.Timestamp.now(tz="America/Bogota").strftime("%d/%m/%Y %H:%M")
        leyenda = f"Firmado el {ahora}" if leyenda_on else ""

        section("4. Vista previa y guardar")
        if not firma:
            st.info("Dibuja la firma y presiona **Usar esta firma** para ver cómo queda.")
        else:
            try:
                firmado = D.estampar_firma(data, firma, int(pagina), x_pct, y_pct, ancho, leyenda)
            except Exception as e:  # noqa: BLE001
                st.error(f"No se pudo estampar la firma: {e}")
                firmado = None
            if firmado:
                st.image(D.render_pagina(firmado, int(pagina)), use_container_width=True,
                         caption=f"Página {int(pagina) + 1} con la firma (así quedará el documento)")
                r1, r2 = st.columns(2)
                r1.download_button("Descargar el PDF firmado para revisar", firmado,
                                   file_name=D.nombre_firmado(fila["nombre"]),
                                   mime="application/pdf", use_container_width=True)
                if r2.button(f"Guardar en '{D.CARPETA_FIRMADOS}'", type="primary",
                             use_container_width=True, disabled=not ok_cf):
                    try:
                        destino = D.carpeta_firmados(USUARIO)
                        nuevo = D.subir(destino, D.nombre_firmado(fila["nombre"]), firmado,
                                        "application/pdf", USUARIO, f"Firma de '{fila['nombre']}'",
                                        firmado_de=int(pdf_id), contrato=ct_f,
                                        firma_pagina=int(pagina) + 1)
                        D.limpiar_firma("doc_firma")
                        st.session_state["doc_carpeta_pendiente"] = destino
                        st.session_state["doc_abrir_pendiente"] = int(nuevo)
                        st.success(f"Guardado en **{D.CARPETA_FIRMADOS}**.")
                        st.rerun()
                    except Exception as e:  # noqa: BLE001
                        st.error(f"No se pudo guardar: {e}")
            st.caption("El original no se modifica: se guarda una copia nueva con la firma. "
                       "Quién firmó y cuándo queda registrado en la base. Es una firma manuscrita "
                       "digitalizada, no una firma digital certificada.")
