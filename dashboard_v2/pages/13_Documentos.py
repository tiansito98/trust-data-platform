"""
Documentos — solo trust_admin (piloto del reemplazo de Odoo Documents).

Pestanas:
  - Contratos: SOLO "nuevo contrato firmado". Primero el CONTRATO (es la llave: unico
    para siempre; la placa puede cambiar a mitad de renta). El asesor sube SOLO el
    contrato; adendum e informacion general salen de las plantillas; una firma se
    estampa en los 3, vista previa, guardar. Sin firma: comprobante de pago y factura
    electronica (se pueden cargar despues). La placa NO se digita: sale del sistema.
  - Validacion: como Facturas. Expediente vs sistema (silver): faltan firmados / falta
    comprobante o factura / pendiente / al dia, y contratos del sistema sin expediente.
  - Plantillas: adendum e informacion general (versionadas) y donde va la firma.
  - Archivos generales: carpetas libres (lo que venga de Odoo, etc.) y los expedientes
    en Contratos / <CONTRATO> (con sus versiones, adjuntos y eliminar). HOJAS DE CALCULO
    (components/hojas.py): crear, abrir los .xlsx y editarlos en la app, guardado solo.

Logica en components/expedientes.py, components/documentos.py y components/storage.py.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import datetime as dt
import math

import pandas as pd
import streamlit as st

from components.common import inject_styles, render_header, section, kpi, fmt_int, xlsx_download_button
from components.auth import require_auth, require_page, logout_button, get_current_user
from components.filters import render_sidebar_filters
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
        "SUPABASE_SERVICE_ROLE_KEY = \"...\"\n```"
    )
    st.stop()

from components import documentos as D   # noqa: E402  (registra el componente de firma)
from components import expedientes as E  # noqa: E402
from components import hojas as H        # noqa: E402

# Streamlit Cloud puede servir modulos viejos tras un push (ver CLAUDE.md): recargarlos.
import importlib  # noqa: E402
# Recarga EN CADENA: documentos y expedientes guardan una referencia al modulo storage, asi
# que si storage esta viejo hay que recargar los tres en orden (storage -> documentos ->
# expedientes). 2026-11-10: "module 'components.storage' has no attribute 'project_ref'".
if (getattr(S, "API_VERSION", 0) < 2 or getattr(D, "API_VERSION", 0) < 6
        or getattr(E, "API_VERSION", 0) < 7):
    S = importlib.reload(S)
    D = importlib.reload(D)
    E = importlib.reload(E)
if getattr(H, "API_VERSION", 0) < 1:
    H = importlib.reload(H)

try:
    E.ensure_tables()
    H.ensure_tables()
except Exception as e:  # noqa: BLE001
    st.error(f"No se pudo preparar Storage / tablas: {e}")
    st.stop()

filtros = render_sidebar_filters(default_days=7)   # lo usa la pestana Validacion

FIRMA_EJEMPLO = {"trazos": [[[40 + i * 4, 100 + 45 * math.sin(i / 4)] for i in range(110)],
                            [[150, 40], [200, 165]]]}


# =============================================================================
# Helpers
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
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return ""
    t = pd.Timestamp(v)
    if t.tzinfo:
        t = t.tz_convert("America/Bogota")
    return t.strftime("%d/%m/%Y %H:%M")


def _placas(v) -> str:
    return ", ".join(v) if isinstance(v, (list, tuple)) and len(v) else ""


@st.cache_data(show_spinner=False, max_entries=16)
def _bytes(path: str) -> bytes:
    return S.download(path)   # storage_path es unico e inmutable: cache seguro


@st.cache_data(show_spinner=False, max_entries=48)
def _png_path(path: str, pagina: int) -> bytes:
    return D.render_pagina(_bytes(path), pagina)


@st.cache_data(show_spinner=False, max_entries=48)
def _png_bytes(data: bytes, pagina: int, ancho: int = 900) -> bytes:
    return D.render_pagina(data, pagina, ancho)


@st.cache_data(show_spinner=False, max_entries=16)
def _npag(path: str) -> int:
    return D.n_paginas(_bytes(path))


def visor(fila, key: str) -> None:
    """Abrir / descargar / vista previa de un documento."""
    try:
        url = S.signed_url(fila["storage_path"], 300)
        url_dl = S.signed_url(fila["storage_path"], 300, descargar_como=fila["nombre"])
    except Exception as e:  # noqa: BLE001
        st.error(f"No se pudo generar el enlace: {e}")
        return
    b1, b2, b3 = st.columns([1, 1, 3])
    b1.link_button("Abrir en pestaña nueva", url, width="stretch")
    b2.link_button("Descargar", url_dl, width="stretch")
    info = [f"Cargado el {_fecha(fila['subido_at'])} por {fila['subido_por']}"]
    if pd.notna(fila.get("firmado_por")) and fila.get("firmado_por"):
        info.append(f"firmado (usuario **{fila['firmado_por']}**, {_fecha(fila['firmado_at'])})")
    b3.caption(" · ".join(info))
    mime = (fila["mime_type"] or "").lower()
    if mime == "application/pdf":
        try:
            n = _npag(fila["storage_path"])
            pg = 1
            if n > 1:
                ini = int(fila["firma_pagina"]) if pd.notna(fila.get("firma_pagina")) else 1
                pg = st.number_input(f"Página (de {n})", 1, n, min(max(ini, 1), n), key=f"{key}_pg")
            st.image(_png_path(fila["storage_path"], int(pg) - 1), width="stretch")
        except Exception as e:  # noqa: BLE001
            st.error(f"No se pudo mostrar el PDF: {e}")
    elif mime.startswith("image/"):
        st.image(url)
    elif mime.startswith("text/") or mime == "application/json":
        st.code(_bytes(fila["storage_path"])[:200_000].decode("utf-8", "replace"))
    else:
        st.caption("Vista previa solo para PDF, imágenes y texto. Usa *Abrir* o *Descargar*.")


SEDE_CORTA = {"BOGOTA": "Bogotá", "MEDELLIN AP": "Medellín aeropuerto", "MEDELLIN CITY": "Medellín Poblado",
              "PEREIRA": "Pereira", "BUCARAMANGA": "Bucaramanga", "CARTAGENA": "Cartagena",
              "SANTA MARTA": "Santa Marta"}


def _sede_corta(s) -> str:
    s = str(s or "")
    return next((v for k, v in SEDE_CORTA.items() if s.upper().startswith(k)), s.title())


def posicion(key: str, n_paginas: int, defaults=(None, 64.0, 8.0, 28.0)):
    """Selector de pagina/posicion/ancho de la firma. Devuelve (pagina 0-based, x, y, ancho)."""
    pg0, x0, y0, a0 = defaults
    c1, c2, c3 = st.columns(3)
    pagina = c1.number_input(f"Página (de {n_paginas})", 1, n_paginas,
                             min(int(pg0), n_paginas) if pg0 else n_paginas, key=f"{key}_pag") - 1
    pos = c2.selectbox("Posición", ["Abajo a la derecha", "Abajo al centro", "Abajo a la izquierda",
                                    "Personalizada"], key=f"{key}_pos")
    ancho = c3.slider("Ancho de la firma (% de la hoja)", 10, 60, int(a0), key=f"{key}_ancho")
    presets = {"Abajo a la derecha": (100 - ancho - 8, 8), "Abajo al centro": ((100 - ancho) / 2, 8),
               "Abajo a la izquierda": (8, 8)}
    if pos == "Personalizada":
        q1, q2 = st.columns(2)
        x = q1.slider("Desde la izquierda (%)", 0, 95, int(x0), key=f"{key}_x")
        y = q2.slider("Desde abajo (%)", 0, 95, int(y0), key=f"{key}_y")
    else:
        x, y = presets[pos]
    return int(pagina), float(x), float(y), float(ancho)


def panel_expediente(exp: dict) -> None:
    """Resumen del expediente cuando la carpeta elegida es la de un contrato."""
    c = int(exp["contrato"])
    tram = E.TRAMITES.get(exp.get("tramite"), E.TRAMITES["RENTA"])
    req = list(exp["requeridos"]) if isinstance(exp.get("requeridos"), (list, tuple))         and len(exp["requeridos"]) else tram["requeridos"]
    docs = E.documentos_contrato(c)
    tipos = set(docs["tipo_documento"])
    section(f"Contrato {c}")
    _info = D.info_contrato(c)
    _pl = _placas(_info["placas"]) if _info else ""
    st.caption(f"{tram['nombre']} · placa(s) **{_pl or 'el contrato aún no llega del sistema'}** · cliente: "
               f"**{exp.get('firmante_nombre') or '-'}** · firmado el "
               f"{_fecha(exp.get('firmado_at') or exp['creado_at'])} · usuario {exp['creado_por']}")
    faltan = [E.TIPOS[x] for x in req if x not in tipos]
    if faltan:
        st.warning("Faltan firmados: " + ", ".join(faltan))
    sin_adj = [v for k, v in E.ADJUNTOS.items() if k not in tipos]
    if sin_adj:
        st.warning("Falta cargar: " + ", ".join(sin_adj) + " (la validación lo pide).")
    with st.expander("Agregar comprobante de pago o factura electrónica"):
        st.caption("Si ya hay uno del mismo tipo, el nuevo lo reemplaza (el anterior queda como versión anterior).")
        an = st.session_state.setdefault(f"adj_nonce_{c}", 0)
        with st.form(f"adj_form_{c}_{an}"):
            q1, q2 = st.columns(2)
            subidos = {t: col.file_uploader(f"{E.ADJUNTOS[t]} (PDF, JPG o PNG)", type=["pdf", "jpg", "jpeg", "png"],
                                            key=f"adj_{t}_{c}_{an}")
                       for col, t in zip((q1, q2), E.ADJUNTOS)}
            ok_a = st.form_submit_button("Guardar")
        if ok_a:
            try:
                adj = [E.adjunto(t, f.name, f.getvalue()) for t, f in subidos.items() if f is not None]
                if not adj:
                    st.error("Elige al menos un archivo.")
                else:
                    E.agregar_adjuntos(c, adj, USUARIO)
                    st.session_state[f"adj_nonce_{c}"] = an + 1
                    st.rerun()
            except Exception as e:  # noqa: BLE001
                st.error(f"No se pudo guardar: {e}")
    viejos = E.documentos_contrato(c, vigentes=False)
    if not viejos.empty:
        with st.expander(f"Versiones anteriores ({len(viejos)})"):
            st.dataframe(pd.DataFrame({
                "Archivo": viejos["nombre"], "Cargado": viejos["subido_at"].map(_fecha),
                "Reemplazado": viejos["eliminado_at"].map(_fecha),
                "Por": viejos["eliminado_por"].fillna("")}), width="stretch", hide_index=True)
            opv = dict(zip(viejos["documento_id"].astype(int), viejos["nombre"]))
            dv = st.selectbox("Ver versión anterior", list(opv), format_func=opv.get, key=f"exp_old_{c}")
            visor(viejos[viejos["documento_id"] == dv].iloc[0], f"old{dv}")
    with st.expander("Eliminar este expediente"):
        st.caption("Para pruebas o errores. Los archivos quedan guardados en el historial, pero el "
                   "contrato vuelve a quedar sin documentos.")
        ok_del = st.checkbox(f"Sí, eliminar el expediente del contrato {c}", key=f"exp_del_ok_{c}")
        if st.button("Eliminar expediente", disabled=not ok_del, key=f"exp_del_{c}"):
            E.eliminar_expediente(c, USUARIO)
            st.rerun()
    section("Archivos")


@st.fragment
def panel_hoja(doc_id: int, nombre: str) -> None:
    """Hoja de calculo: la abre editable si nadie mas la tiene; si no, en solo lectura.
    Se guarda sola (cada cambio, 1,5 s despues). Fragmento: el autoguardado solo
    re-ejecuta este bloque, no toda la pagina."""
    k = f"hoja_{doc_id}"
    ses = st.session_state.get(k)
    if ses is None:                                   # abrir (una vez por sesion de la hoja)
        solo_ver = st.session_state.pop(f"{k}_solo_ver", False)
        ok = False if solo_ver else H.tomar(doc_id, USUARIO)[0]
        ses = {"nonce": st.session_state.get(f"{k}_n", 0), "modo": "editar" if ok else "ver",
               "ini": H.datos_iniciales(H.abrir(doc_id)), "seq": 0, "guardado": None, "perdida": False}
        st.session_state[k] = ses
    est = H.estado(doc_id)
    otro = bool(est.get("tomada")) and est.get("editor") != USUARIO

    def _reabrir(solo_ver: bool = False) -> None:
        st.session_state[f"{k}_n"] = ses["nonce"] + 1
        st.session_state.pop(k, None)
        if solo_ver:
            st.session_state[f"{k}_solo_ver"] = True
        st.rerun(scope="fragment")

    c1, c2, c3 = st.columns([4, 1, 1])
    if ses["modo"] == "editar":
        if ses["perdida"]:
            c1.error("Otra persona tomó la hoja mientras estaba quieta: tus últimos cambios NO se guardaron. "
                     "Descárgala (Archivo → Descargar como Excel) si los necesitas y vuelve a abrirla.")
        else:
            g = ses["guardado"]
            c1.caption("**Editando.** Se guarda sola mientras escribes"
                       + (f" · último guardado {g}" if g else "") + ".")
        if c2.button("Terminar edición", key=f"{k}_fin", width="stretch"):
            H.soltar(doc_id, USUARIO)
            _reabrir(solo_ver=True)
    else:
        if otro:
            c1.warning(f"La está editando **{est['editor']}**: la ves en solo lectura. "
                       f"Presiona *Actualizar* para ver sus cambios.")
        else:
            c1.caption("Solo lectura.")
        if c2.button("Actualizar", key=f"{k}_upd", width="stretch"):
            _reabrir(solo_ver=True)
        if not otro and c3.button("Editar", key=f"{k}_edit", type="primary", width="stretch"):
            _reabrir()

    ev = H.editor(f"{k}_{ses['nonce']}", nombre, ses["ini"], solo_lectura=ses["modo"] != "editar")
    if ses["modo"] == "editar" and isinstance(ev, dict) and ev.get("tipo") == "guardar" \
            and int(ev.get("seq", 0)) > ses["seq"]:
        ses["seq"] = int(ev["seq"])
        if H.guardar(doc_id, USUARIO, ev["data"]):
            ses["guardado"] = pd.Timestamp.now(tz="America/Bogota").strftime("%H:%M:%S")
        else:
            ses["perdida"] = True
        st.rerun(scope="fragment")

    with st.expander("Versiones anteriores"):
        st.caption("Se guarda una versión cada vez que alguien empieza a editar.")
        v = H.versiones(doc_id)
        if v.empty:
            st.caption("Todavía no hay versiones anteriores.")
        else:
            opv = {int(r.version_id): f"{_fecha(r.creado_at)} · {r.motivo}" for r in v.itertuples()}
            vid = st.selectbox("Versión", list(opv), format_func=opv.get, key=f"{k}_ver")
            if st.button("Volver a esta versión", key=f"{k}_rest"):
                if H.restaurar(doc_id, vid, USUARIO):
                    _reabrir()
                else:
                    st.error("No se puede: otra persona la está editando.")


tab_con, tab_val, tab_pla, tab_gen = st.tabs(["Contratos", "Validación", "Plantillas", "Archivos generales"])

# =============================================================================
# CONTRATOS: solo "nuevo contrato firmado". Los expedientes se ven en Archivos
# generales -> Contratos / <CONTRATO> (el contrato es la llave, no la placa).
# =============================================================================
with tab_con:
    _flash = st.session_state.pop("exp_flash", None)
    if _flash:
        st.success(_flash)

    nonce = st.session_state.setdefault("exp_nonce", 0)
    pla_all = E.plantillas_activas()

    section("1. Contrato y trámite")
    c1, _c2 = st.columns(2)
    ctxt = c1.text_input("Número de contrato (10 dígitos)", key=f"exp_ct_{nonce}").strip()
    ok_datos = True
    info = None
    if ctxt and not E.contrato_valido(ctxt):
        c1.error("El contrato son 10 dígitos.")
        ok_datos = False
    elif ctxt:
        info = D.info_contrato(int(ctxt))

    if ctxt and ok_datos:
        if info is None:
            st.caption("El contrato todavía no está en el sistema (llega con el pipeline de la madrugada); "
                       "la placa se toma de ahí. Se valida después en *Validación*.")
        else:
            st.caption(f"Contrato en el sistema: {_sede_corta(info['sede'])} · entrega {info['entrega']} · "
                       f"placa(s) {_placas(info['placas']) or '-'}.")
        ex = E.expediente(int(ctxt))
        if ex:
            st.warning("Este contrato ya tiene documentos: al guardar se reemplazan por los nuevos (los "
                       "anteriores quedan como *versiones anteriores*). Para solo agregar el comprobante o la "
                       "factura, ve a *Archivos generales* → *Contratos / " + ctxt + "*.")

    tramite = st.radio("Trámite", list(E.TRAMITES), format_func=lambda k: E.TRAMITES[k]["nombre"],
                       horizontal=True, key=f"exp_tramite_{nonce}")
    es_renta = tramite == "RENTA"
    firmante, idioma = "", None
    if es_renta:
        d1, d2 = st.columns([2, 1])
        firmante = d1.text_input("Nombre del cliente (como queda en el addendum)",
                                 key=f"exp_nombre_{nonce}").strip().upper()
        idioma = d2.radio("Idioma de la información de renta", list(E.IDIOMAS),
                          format_func=E.IDIOMAS.get, horizontal=True, key=f"exp_idioma_{nonce}")
    ok_datos = ok_datos and bool(ctxt) and (bool(firmante) or not es_renta)
    if ctxt and es_renta and not firmante:
        st.info("Escribe el nombre del cliente.")

    pla = E.plantillas_del_tramite(tramite, idioma or "ES", pla_all)
    if es_renta:
        lleva = ["Contrato"] + [E.etiqueta(p.tipo, p.idioma if isinstance(p.idioma, str) else None)
                                for p in pla.itertuples()]
        st.caption("Se firman: **" + "**, **".join(lleva) + "**")
        if len(pla) < len(E.TIPOS_PLANTILLA):
            st.warning("Falta cargar alguna plantilla (pestaña *Plantillas*): el contrato quedará incompleto.")

    section("2. Sube el contrato (PDF)")
    up = st.file_uploader("Contrato", type=["pdf"], key=f"exp_file_{nonce}")
    contrato_pdf = up.getvalue() if up else None
    n_pag = 0
    if contrato_pdf:
        try:
            n_pag = len(D.info_pdf(contrato_pdf))
        except Exception as e:  # noqa: BLE001
            st.error(f"Ese PDF no se puede leer: {e}")
            contrato_pdf = None

    st.markdown("**Documentos que no se firman**: comprobante de pago y factura electrónica. Se guardan tal cual "
                "en la carpeta del contrato; si aún no los tienes, se pueden cargar después desde *Archivos "
                "generales*, pero la *Validación* los pide.")
    a1, a2 = st.columns(2)
    adjuntos, ok_adj = [], True
    for col, tipo_a in zip((a1, a2), E.ADJUNTOS):
        fa = col.file_uploader(f"{E.ADJUNTOS[tipo_a]} (PDF, JPG o PNG)", type=["pdf", "jpg", "jpeg", "png"],
                               key=f"exp_adj_{tipo_a}_{nonce}")
        if fa is not None:
            try:
                adjuntos.append(E.adjunto(tipo_a, fa.name, fa.getvalue()))
            except Exception as e:  # noqa: BLE001
                col.error(f"No se puede usar ese archivo: {e}")
                ok_adj = False

    if contrato_pdf and ok_datos and ok_adj:
        section("3. Firma del cliente (con el mouse o el dedo)")
        firma = D.panel_firma(f"exp_firma_{nonce}")

        section("4. Dónde va la firma en el contrato")
        pg, x, y, an = posicion(f"exp_pos_{nonce}", n_pag)
        if es_renta:
            st.caption("En el addendum y la información de renta la firma (y el nombre) van donde lo "
                       "define la plantilla.")

        if not firma:
            st.info("Dibuja la firma y presiona **Usar esta firma** para ver cómo quedan los documentos.")
        else:
            section("5. Vista previa: así quedan los documentos")
            ahora = pd.Timestamp.now(tz="America/Bogota")
            valores = {"nombre": firmante, "contrato": ctxt, "fecha": f"{ahora:%d/%m/%Y}"}
            try:
                prep = E.preparar(contrato_pdf, firma, {"pagina": pg, "x": x, "y": y, "ancho": an},
                                  valores, f"Firmado el {ahora:%d/%m/%Y %H:%M}", pla, _bytes)
            except Exception as e:  # noqa: BLE001
                st.error(f"No se pudo estampar la firma: {e}")
                prep = []
            if prep:
                cols = st.columns(len(prep))
                for col, item in zip(cols, prep):
                    with col:
                        st.markdown(f"**{E.etiqueta(item['tipo'], item['idioma'])}** · "
                                    f"pág. {item['pagina'] + 1}")
                        st.image(_png_bytes(item["firmado"], item["pagina"]), width="stretch")
                        st.download_button(
                            "Descargar", item["firmado"],
                            file_name=E.nombre_archivo(int(ctxt), item["tipo"], ahora.date(), item["idioma"]),
                            mime="application/pdf", key=f"exp_dl_{item['tipo']}_{nonce}", width="stretch")
                if adjuntos:
                    st.caption("Además se guardan sin firmar: " +
                               ", ".join(E.ADJUNTOS[a["tipo"]] for a in adjuntos) + ".")
                if st.button("Guardar los documentos", type="primary", key=f"exp_save_{nonce}"):
                    try:
                        with st.spinner("Guardando..."):
                            ids = E.guardar(int(ctxt), prep, USUARIO, tramite, firmante, idioma,
                                            adjuntos=adjuntos)
                        D.limpiar_firma(f"exp_firma_{nonce}")
                        st.session_state["exp_nonce"] = nonce + 1
                        exp_n = E.expediente(int(ctxt))
                        st.session_state["doc_carpeta_pendiente"] = int(exp_n["carpeta_id"])
                        st.session_state["exp_flash"] = (
                            f"Guardado: {len(ids)} documento(s) del contrato {ctxt} en "
                            f"**Contratos / {ctxt}**. Para verlos: pestaña *Archivos generales* "
                            f"(ya queda seleccionada esa carpeta).")
                        st.rerun()
                    except Exception as e:  # noqa: BLE001
                        st.error(f"No se pudo guardar: {e}")

# =============================================================================
# VALIDACION
# =============================================================================
with tab_val:
    st.caption(f"Rango del filtro lateral ({filtros.fecha_desde} → {filtros.fecha_hasta}). Expedientes firmados "
               f"en el rango + contratos del sistema entregados en el rango sin documentos (desde "
               f"{E.FECHA_INICIO:%d/%m/%Y}, cuando arranca el uso).")
    try:
        val = E.validacion(filtros.fecha_desde, filtros.fecha_hasta, filtros.sedes_nombres or None)
    except Exception as e:  # noqa: BLE001
        st.error(f"No se pudo validar: {e}")
        val = pd.DataFrame()
    if val.empty:
        st.info("No hay contratos en el rango.")
    else:
        cnt = val["estado"].value_counts()
        ks = st.columns(5)
        for col, k in zip(ks, ["OK", "PENDIENTE", "INCOMPLETO", "FALTA_ADJ", "SIN_DOCS"]):
            kpi(col, E.ESTADOS[k], fmt_int(int(cnt.get(k, 0))))
        ver = st.radio("Mostrar", ["Con problemas", "Todos", "Al día", "Pendientes"], horizontal=True,
                       key="exp_val_ver")
        t = {"Con problemas": val[val["estado"].isin(["INCOMPLETO", "FALTA_ADJ", "SIN_DOCS"])],
             "Todos": val, "Al día": val[val["estado"] == "OK"],
             "Pendientes": val[val["estado"] == "PENDIENTE"]}[ver]
        orden = {"INCOMPLETO": 0, "FALTA_ADJ": 1, "SIN_DOCS": 2, "PENDIENTE": 3, "OK": 4}
        t = t.assign(_o=t["estado"].map(orden)).sort_values(["_o", "contrato"])
        vista = pd.DataFrame({
            "Estado": t["estado"].map(E.ESTADOS),
            "Contrato": t["contrato"].astype(str),
            "Placa(s) en el sistema": t["placas_sistema"],
            "Sede": t["sede"].fillna(""),
            "Entrega": t["entrega"].map(lambda v: "" if v is None or pd.isna(v) else str(v)),
            "Trámite": t["tramite"],
            "Cliente": t["firmante"],
            "Faltan": t["faltan"],
            "Usuario": t["creado_por"],
            "Firmado": t["creado_at"].map(_fecha),
        })
        st.dataframe(vista, width="stretch", hide_index=True)
        xlsx_download_button(vista, file_name=f"validacion_contratos_{dt.date.today()}",
                             sheet_name="Validacion", key="xlsx_exp_val")


# =============================================================================
# PLANTILLAS
# =============================================================================
with tab_pla:
    st.caption("Documentos iguales para TODOS los contratos de renta. Cada carga es una versión nueva; los "
               "contratos ya firmados conservan la versión con la que se firmaron.")
    pla = E.plantillas_activas()
    VALORES_EJEMPLO = {"nombre": "NOMBRE DEL CLIENTE", "contrato": "9520000000", "fecha": "dd/mm/aaaa"}
    COLS_CAMPOS = ["tipo", "valor", "pagina", "x", "y", "ancho", "alto", "size", "leyenda"]
    for p in pla.itertuples():
        idi = p.idioma if isinstance(p.idioma, str) else None
        section(E.etiqueta(p.tipo, idi))
        data = _bytes(p.storage_path)
        n = len(D.info_pdf(data))
        st.caption(f"Versión **{int(p.version)}** · {p.nombre} · {n} página(s) · cargada el "
                   f"{_fecha(p.subido_at)} por {p.subido_por}")
        campos = E.campos_para_estampar(p.campos, n, VALORES_EJEMPLO, "Firmado el dd/mm/aaaa hh:mm")
        pgs = sorted({c["pagina"] for c in campos}) or [n - 1]
        cols = st.columns(len(pgs))
        for col, pg in zip(cols, pgs):
            col.image(_png_bytes(D.estampar_campos(data, FIRMA_EJEMPLO, campos), pg, 700),
                      caption=f"Página {pg + 1} con datos de ejemplo", width="stretch")
        with st.expander("Ajustar los campos (posición en % de la hoja; y se mide desde abajo)"):
            st.caption("tipo = firma | texto · valor (textos) = nombre | contrato | fecha · página desde 1 · "
                       "ancho/alto de la firma en % · size = tamaño de letra · leyenda = 'Firmado el ...' bajo la firma.")
            df_c = pd.DataFrame([{k: c.get(k) for k in COLS_CAMPOS} for c in p.campos], columns=COLS_CAMPOS)
            ed = st.data_editor(df_c, num_rows="dynamic", width="stretch", key=f"pla_ed_{p.plantilla_id}",
                                column_config={
                                    "tipo": st.column_config.SelectboxColumn(options=["firma", "texto"], required=True),
                                    "valor": st.column_config.SelectboxColumn(options=["nombre", "contrato", "fecha"]),
                                    "leyenda": st.column_config.CheckboxColumn()})
            if st.button("Guardar campos", key=f"pla_ed_btn_{p.plantilla_id}"):
                nuevos = []
                for r in ed.to_dict("records"):
                    if r.get("tipo") not in ("firma", "texto"):
                        continue
                    c = {"tipo": r["tipo"], "pagina": int(r["pagina"] or n), "x": float(r["x"] or 0),
                         "y": float(r["y"] or 0)}
                    if r["tipo"] == "firma":
                        c.update({"ancho": float(r["ancho"] or 20), "alto": float(r["alto"]) if pd.notna(r["alto"]) else None,
                                  "leyenda": bool(r["leyenda"]) if pd.notna(r["leyenda"]) else False})
                    else:
                        c.update({"valor": r.get("valor") or "nombre",
                                  "size": float(r["size"]) if pd.notna(r["size"]) else 9})
                    nuevos.append(c)
                E.actualizar_campos(int(p.plantilla_id), nuevos)
                st.success("Campos guardados.")
                st.rerun()

    section("Cargar una plantilla nueva o una versión nueva")
    u1, u2 = st.columns(2)
    tipo_n = u1.selectbox("Documento", list(E.TIPOS_PLANTILLA), format_func=E.TIPOS.get, key="pla_new_tipo")
    idi_n = u2.selectbox("Idioma", [None, "ES", "EN"],
                         format_func=lambda i: "Único (sin idioma)" if i is None else E.IDIOMAS[i], key="pla_new_idi")
    f = st.file_uploader("PDF (si lo tienes en Word: Archivo → Guardar como → PDF)", type=["pdf"], key="pla_new_up")
    if f is not None and st.button("Cargar", key="pla_new_btn"):
        try:
            E.subir_plantilla(tipo_n, idi_n, f.name, f.getvalue(), USUARIO)
            st.success("Plantilla cargada. Si es nueva, revisa y ajusta los campos arriba.")
            st.rerun()
        except Exception as e:  # noqa: BLE001
            st.error(f"No se pudo cargar: {e}")
    hist = E.historial_plantillas()
    if not hist.empty:
        with st.expander("Historial de versiones"):
            st.dataframe(pd.DataFrame({
                "Documento": [E.etiqueta(tp, i if isinstance(i, str) else None)
                              for tp, i in zip(hist["tipo"], hist["idioma"])],
                "Versión": hist["version"], "Archivo": hist["nombre"],
                "Activa": hist["activa"].map({True: "Sí", False: ""}), "Cargada por": hist["subido_por"],
                "Cargada": hist["subido_at"].map(_fecha)}), width="stretch", hide_index=True)

# =============================================================================
# ARCHIVOS GENERALES (carpetas libres)
# =============================================================================
with tab_gen:
    df_c = D.carpetas()
    rutas = D.rutas_carpetas(df_c) if not df_c.empty else {}
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
                            if st.session_state.get("doc_carpeta") is not None:   # ver hoja nueva
                                st.session_state["doc_carpeta_pendiente"] = st.session_state["doc_carpeta"]
                            st.rerun()
                        except Exception as e:  # noqa: BLE001
                            st.error("Ya existe una carpeta con ese nombre ahí." if "unique" in str(e).lower()
                                     else f"No se pudo crear: {e}")
        if rutas:
            with st.expander("Nueva hoja de cálculo"):
                with st.form("doc_new_sheet", clear_on_submit=True):
                    nombre_h = st.text_input("Nombre (ej. FOTOMULTAS 2027)")
                    st.caption("Se crea en la carpeta seleccionada.")
                    if st.form_submit_button("Crear hoja"):
                        try:
                            cp = int(st.session_state["doc_carpeta"])
                            nid = H.crear(cp, nombre_h, USUARIO)
                            # el rerun corta el script ANTES del selector de carpeta y Streamlit
                            # borra su estado: se re-aplica con el "pendiente"
                            st.session_state["doc_carpeta_pendiente"] = cp
                            st.session_state["doc_abrir_pendiente"] = nid
                            st.rerun()
                        except Exception as e:  # noqa: BLE001
                            st.error(f"No se pudo crear: {e}")
    if not rutas:
        st.info("Todavía no hay carpetas.")
    else:
        with c_sel:
            _pc = st.session_state.pop("doc_carpeta_pendiente", None)
            if _pc in rutas:
                st.session_state["doc_carpeta"] = _pc
            elif st.session_state.get("doc_carpeta") not in rutas:
                st.session_state.pop("doc_carpeta", None)
            carpeta = st.selectbox("Carpeta (escribe el número de contrato para buscarlo)", list(rutas),
                                   format_func=lambda c: rutas[c], key="doc_carpeta")
        exp_c = E.expediente_de_carpeta(carpeta)
        if exp_c:
            panel_expediente(exp_c)
        docs = D.documentos(carpeta)
        if docs.empty:
            st.info("La carpeta está vacía.")
        else:
            st.dataframe(pd.DataFrame({
                "Documento": [E.etiqueta(t) if isinstance(t, str) else
                              ("Hoja de cálculo" if m == H.HOJA_MIME else "")
                              for t, m in zip(docs["tipo_documento"], docs["mime_type"])],
                "Nombre": docs["nombre"],
                "Contrato": docs["contrato"].map(lambda v: "" if pd.isna(v) else str(int(v))),
                "Tamaño": docs["tamano_bytes"].map(_tam),
                "Cargado por": docs["subido_por"],
                "Cargado": docs["subido_at"].map(_fecha),
            }), width="stretch", hide_index=True)
            op = dict(zip(docs["documento_id"].astype(int), docs["nombre"]))
            _pa = st.session_state.pop("doc_abrir_pendiente", None)
            if _pa in op:
                st.session_state["doc_abrir"] = _pa
            elif st.session_state.get("doc_abrir") not in op:
                st.session_state.pop("doc_abrir", None)
            doc_id = st.selectbox("Ver archivo", list(op), format_func=op.get, key="doc_abrir")
            fila = docs[docs["documento_id"] == doc_id].iloc[0]
            # si deja una hoja que estaba editando, suelta el turno
            _prev = st.session_state.get("hoja_abierta")
            if _prev and _prev != doc_id:
                ps = st.session_state.pop(f"hoja_{_prev}", None)
                if ps and ps.get("modo") == "editar":
                    H.soltar(_prev, USUARIO)
                    st.session_state[f"hoja_{_prev}_n"] = ps["nonce"] + 1
            st.session_state["hoja_abierta"] = int(doc_id) if H.es_hoja(fila) else None
            if H.es_hoja(fila):
                panel_hoja(int(doc_id), fila["nombre"])
            else:
                visor(fila, f"g{doc_id}")
                if H.es_xlsx(fila):
                    if st.button("Abrir y editar en la app", key=f"doc_conv_{doc_id}", type="primary"):
                        try:
                            nid = H.convertir_xlsx(fila.to_dict() | {"carpeta_id": carpeta}, USUARIO)
                            st.session_state["doc_abrir_pendiente"] = nid
                            st.rerun()
                        except Exception as e:  # noqa: BLE001
                            st.error(f"No se pudo abrir: {e}")
                    st.caption("La convierte en una hoja de cálculo de la app (fórmulas, pestañas y formato) "
                               "que se edita aquí y se guarda sola. El .xlsx original queda en el historial.")
            # los firmados del expediente no se borran sueltos (eliminar expediente arriba);
            # los adjuntos y los archivos libres si
            if pd.isna(fila.get("tipo_documento")) or fila.get("tipo_documento") in E.ADJUNTOS:
                with st.expander("Eliminar este archivo"):
                    seguro = st.checkbox(f"Sí, eliminar '{fila['nombre']}'", key=f"doc_del_ok_{doc_id}")
                    if st.button("Eliminar", disabled=not seguro, key=f"doc_del_{doc_id}"):
                        D.eliminar(doc_id, USUARIO)
                        st.rerun()

        with st.expander(f"Subir archivos a {rutas[carpeta]}"):
            gn = st.session_state.setdefault("doc_up_nonce", 0)
            with st.form(f"doc_upload_{gn}"):
                files = st.file_uploader("Archivos (máx. 50 MB c/u)", accept_multiple_files=True,
                                         key=f"doc_files_{gn}")
                ok = st.form_submit_button("Subir")
            if ok and files:
                errores = []
                for f in files:
                    data = f.getvalue()
                    if len(data) > 50 * 1024 * 1024:
                        errores.append(f"{f.name}: pesa más de 50 MB")
                        continue
                    try:
                        D.subir(carpeta, f.name, data, f.type or "application/octet-stream", USUARIO)
                    except Exception as e:  # noqa: BLE001
                        errores.append(f"{f.name}: {e}")
                for e in errores:
                    st.error(e)
                if not errores:
                    st.session_state["doc_up_nonce"] = gn + 1
                    st.rerun()
