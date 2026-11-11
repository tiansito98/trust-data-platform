"""
Documentos — solo trust_admin (piloto del reemplazo de Odoo Documents).

Pestanas:
  - Contratos: buscar por placa o contrato (Contratos / PLACA / CONTRATO) y crear un
    expediente nuevo: el asesor sube SOLO el contrato; adendum e informacion general
    salen de las plantillas; una firma se estampa en los 3, vista previa, guardar.
  - Validacion: como Facturas. Expediente vs sistema (silver): pendiente / placa no
    coincide / faltan documentos / al dia, y contratos del sistema sin expediente.
  - Plantillas: adendum e informacion general (versionadas) y donde va la firma.
  - Archivos generales: carpetas libres (lo que venga de Odoo, etc.).

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

# Streamlit Cloud puede servir modulos viejos tras un push (ver CLAUDE.md): recargarlos.
import importlib  # noqa: E402
if getattr(D, "API_VERSION", 0) < 5:
    D = importlib.reload(D)
if getattr(E, "API_VERSION", 0) < 3:
    E = importlib.reload(E)

try:
    E.ensure_tables()
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


tab_con, tab_val, tab_pla, tab_gen = st.tabs(["Contratos", "Validación", "Plantillas", "Archivos generales"])

# =============================================================================
# CONTRATOS
# =============================================================================
with tab_con:
    _pend_modo = st.session_state.pop("exp_modo_pendiente", None)
    if _pend_modo:
        st.session_state["exp_modo"] = _pend_modo
    _pend_q = st.session_state.pop("exp_q_pendiente", None)
    if _pend_q:
        st.session_state["exp_q"] = _pend_q
    modo = st.radio("Modo", ["Buscar placa o contrato", "Nuevo contrato firmado"], horizontal=True,
                    key="exp_modo", label_visibility="collapsed")

    # ---------------------------------------------------------------- Buscar
    if modo == "Buscar placa o contrato":
        q = st.text_input("Placa o número de contrato", key="exp_q", placeholder="ej. QQT750 o 9525194370")
        t = E.normalizar_placa(q)
        contrato_sel = None
        if t.isdigit():
            if E.expediente(int(t)):
                contrato_sel = int(t)
            else:
                st.info("Ese contrato no tiene documentos todavía.")
        elif t:
            exps = E.contratos_de_placa(t)
            if exps.empty:
                st.info(f"No hay contratos con documentos para la placa {t}.")
            else:
                section(f"Placa {t}: {len(exps)} contrato(s), del más reciente al más viejo")
                n_req = exps["requeridos"].map(lambda r: len(r) if isinstance(r, (list, tuple)) and len(r) else 3)
                st.dataframe(pd.DataFrame({
                    "": ["Más reciente"] + [""] * (len(exps) - 1),
                    "Firmado": exps["firmado_at"].map(_fecha),
                    "Contrato": exps["contrato"].astype(str),
                    "Trámite": exps["tramite"].map(lambda x: E.TRAMITES.get(x, {}).get("nombre", "")),
                    "Cliente": exps["firmante_nombre"].fillna(""),
                    "Documentos": exps["firmados"].astype(int).astype(str) + " de " + n_req.astype(str),
                    "Usuario": exps["creado_por"],
                }), width="stretch", hide_index=True)
                op_c = {int(r.contrato): f"{_fecha(r.firmado_at)[:10]} · {int(r.contrato)}"
                        for r in exps.itertuples()}
                contrato_sel = st.selectbox("Contrato", list(op_c), format_func=op_c.get, key="exp_sel")

        if contrato_sel:
            exp = E.expediente(contrato_sel)
            docs = E.documentos_contrato(contrato_sel)
            tram = E.TRAMITES.get(exp.get("tramite"), E.TRAMITES["RENTA"])
            req = list(exp["requeridos"]) if isinstance(exp.get("requeridos"), (list, tuple)) \
                and len(exp["requeridos"]) else tram["requeridos"]
            section(f"Contrato {contrato_sel} · placa {exp['placa']}")
            st.caption(f"{tram['nombre']} · cliente: **{exp.get('firmante_nombre') or '-'}** · firmado el "
                       f"{_fecha(exp.get('firmado_at') or exp['creado_at'])} · usuario {exp['creado_por']}")
            faltan = [E.TIPOS[x] for x in req if x not in set(docs["tipo_documento"])]
            if faltan:
                st.warning("Faltan: " + ", ".join(faltan))
            st.dataframe(pd.DataFrame({
                "Documento": [E.etiqueta(tp, i if isinstance(i, str) else None)
                              for tp, i in zip(docs["tipo_documento"], docs["idioma"])],
                "Archivo": docs["nombre"],
                "Cargado": docs["subido_at"].map(_fecha),
                "Usuario": docs["subido_por"],
                "Plantilla": docs["plantilla_version"].map(lambda v: "" if pd.isna(v) else f"v{int(v)}"),
                "Tamaño": docs["tamano_bytes"].map(_tam),
            }), width="stretch", hide_index=True)
            if not docs.empty:
                op = dict(zip(docs["documento_id"].astype(int), docs["nombre"]))
                did = st.selectbox("Ver documento", list(op), format_func=op.get, key=f"exp_ver_{contrato_sel}")
                visor(docs[docs["documento_id"] == did].iloc[0], f"exp{did}")
            viejos = E.documentos_contrato(contrato_sel, vigentes=False)
            if not viejos.empty:
                with st.expander(f"Versiones anteriores ({len(viejos)})"):
                    st.dataframe(pd.DataFrame({
                        "Archivo": viejos["nombre"], "Cargado": viejos["subido_at"].map(_fecha),
                        "Reemplazado": viejos["eliminado_at"].map(_fecha),
                        "Por": viejos["eliminado_por"].fillna("")}), width="stretch", hide_index=True)
                    opv = dict(zip(viejos["documento_id"].astype(int), viejos["nombre"]))
                    dv = st.selectbox("Ver versión anterior", list(opv), format_func=opv.get,
                                      key=f"exp_old_{contrato_sel}")
                    visor(viejos[viejos["documento_id"] == dv].iloc[0], f"old{dv}")
            with st.expander("Eliminar este expediente"):
                st.caption("Para pruebas o errores. Los archivos quedan guardados en el historial, pero el "
                           "contrato vuelve a quedar sin documentos.")
                ok_del = st.checkbox(f"Sí, eliminar el expediente del contrato {contrato_sel}",
                                     key=f"exp_del_ok_{contrato_sel}")
                if st.button("Eliminar expediente", disabled=not ok_del, key=f"exp_del_{contrato_sel}"):
                    E.eliminar_expediente(contrato_sel, USUARIO)
                    st.session_state["exp_q_pendiente"] = exp["placa"]
                    st.rerun()

    # ---------------------------------------------------------------- Nuevo
    else:
        nonce = st.session_state.setdefault("exp_nonce", 0)
        pla_all = E.plantillas_activas()

        section("1. Placa, contrato y trámite")
        c1, c2 = st.columns(2)
        placa = E.normalizar_placa(c1.text_input("Placa", key=f"exp_placa_{nonce}", placeholder="ABC123"))
        ctxt = c2.text_input("Número de contrato (10 dígitos)", key=f"exp_ct_{nonce}").strip()
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
        ok_datos = True
        if placa and not E.placa_valida(placa):
            c1.error("La placa debe ser 3 letras y 3 números (ej. ABC123).")
            ok_datos = False
        if ctxt and not E.contrato_valido(ctxt):
            c2.error("El contrato son 10 dígitos.")
            ok_datos = False
        ok_datos = ok_datos and bool(placa) and bool(ctxt) and (bool(firmante) or not es_renta)
        if placa and ctxt and es_renta and not firmante:
            st.info("Escribe el nombre del cliente.")
        if placa and ctxt and E.placa_valida(placa) and E.contrato_valido(ctxt):
            info = D.info_contrato(int(ctxt))
            if info is None:
                st.caption("El contrato todavía no está en el sistema (llega con el pipeline de la "
                           "madrugada). Se valida después en *Validación*.")
            elif placa not in info["placas"]:
                st.error(f"Según el sistema, el contrato {ctxt} es de la placa "
                         f"**{_placas(info['placas']) or '-'}**, no {placa}. Revisa antes de firmar.")
            else:
                st.caption(f"Contrato en el sistema: {info['sede']} · entrega {info['entrega']} · placa OK.")
            ex = E.expediente(int(ctxt))
            if ex:
                if ex["placa"] != placa:
                    st.error(f"Ese contrato ya tiene documentos con la placa {ex['placa']}.")
                    ok_datos = False
                else:
                    st.warning("Este contrato ya tiene documentos: al guardar se reemplazan por los nuevos "
                               "(los anteriores quedan como *versiones anteriores*).")

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

        if contrato_pdf and ok_datos:
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
                                file_name=E.nombre_archivo(int(ctxt), placa, item["tipo"], ahora.date(),
                                                           item["idioma"]),
                                mime="application/pdf", key=f"exp_dl_{item['tipo']}_{nonce}", width="stretch")
                    if st.button("Guardar los documentos firmados", type="primary", key=f"exp_save_{nonce}"):
                        try:
                            with st.spinner("Guardando..."):
                                E.guardar(int(ctxt), placa, prep, USUARIO, tramite, firmante, idioma)
                            D.limpiar_firma(f"exp_firma_{nonce}")
                            st.session_state["exp_nonce"] = nonce + 1
                            st.session_state["exp_modo_pendiente"] = "Buscar placa o contrato"
                            st.session_state["exp_q_pendiente"] = placa
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
        for col, k in zip(ks, ["OK", "PENDIENTE", "PLACA", "INCOMPLETO", "SIN_DOCS"]):
            kpi(col, E.ESTADOS[k], fmt_int(int(cnt.get(k, 0))))
        ver = st.radio("Mostrar", ["Con problemas", "Todos", "Al día", "Pendientes"], horizontal=True,
                       key="exp_val_ver")
        t = {"Con problemas": val[val["estado"].isin(["PLACA", "INCOMPLETO", "SIN_DOCS"])],
             "Todos": val, "Al día": val[val["estado"] == "OK"],
             "Pendientes": val[val["estado"] == "PENDIENTE"]}[ver]
        orden = {"PLACA": 0, "INCOMPLETO": 1, "SIN_DOCS": 2, "PENDIENTE": 3, "OK": 4}
        t = t.assign(_o=t["estado"].map(orden)).sort_values(["_o", "contrato"])
        vista = pd.DataFrame({
            "Estado": t["estado"].map(E.ESTADOS),
            "Contrato": t["contrato"].astype(str),
            "Placa digitada": t["placa_digitada"],
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

        malas = val[val["estado"] == "PLACA"]
        if not malas.empty:
            with st.expander(f"Corregir placa ({len(malas)} contrato(s) con placa distinta al sistema)"):
                cm = st.selectbox("Contrato", malas["contrato"].astype(int).tolist(), key="exp_fix_ct")
                fm = malas[malas["contrato"] == cm].iloc[0]
                opciones = [p.strip() for p in fm["placas_sistema"].split(",") if p.strip()]
                nueva = st.selectbox(f"Placa correcta (digitada: {fm['placa_digitada']})", opciones,
                                     key="exp_fix_pl")
                if st.button("Corregir", key="exp_fix_btn"):
                    E.corregir_placa(int(cm), nueva, USUARIO)
                    st.success(f"Contrato {cm} movido a la placa {nueva}.")
                    st.rerun()

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
                            st.rerun()
                        except Exception as e:  # noqa: BLE001
                            st.error("Ya existe una carpeta con ese nombre ahí." if "unique" in str(e).lower()
                                     else f"No se pudo crear: {e}")
    if not rutas:
        st.info("Todavía no hay carpetas.")
    else:
        with c_sel:
            carpeta = st.selectbox("Carpeta", list(rutas), format_func=lambda c: rutas[c], key="doc_carpeta")
        docs = D.documentos(carpeta)
        if docs.empty:
            st.info("La carpeta está vacía.")
        else:
            st.dataframe(pd.DataFrame({
                "Nombre": docs["nombre"],
                "Contrato": docs["contrato"].map(lambda v: "" if pd.isna(v) else str(int(v))),
                "Tamaño": docs["tamano_bytes"].map(_tam),
                "Cargado por": docs["subido_por"],
                "Cargado": docs["subido_at"].map(_fecha),
            }), width="stretch", hide_index=True)
            op = dict(zip(docs["documento_id"].astype(int), docs["nombre"]))
            doc_id = st.selectbox("Ver archivo", list(op), format_func=op.get, key="doc_abrir")
            fila = docs[docs["documento_id"] == doc_id].iloc[0]
            visor(fila, f"g{doc_id}")
            if pd.isna(fila.get("tipo_documento")):   # los de un expediente se manejan en Contratos
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
