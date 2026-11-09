"""
Gestor de documentos (reemplazo de Odoo Documents) sobre Supabase Storage.

  - operational.doc_carpetas : arbol de carpetas (parent_id), como los workspaces
    de Odoo. odoo_folder_id queda para la migracion (idempotencia).
  - operational.documentos   : indice de archivos. El binario vive en el bucket
    privado 'documentos' (components/storage.py) en storage_path; la tabla es la
    fuente de verdad de nombre, carpeta, quien lo subio, firma, etc.
    odoo_attachment_id UNIQUE = clave de idempotencia para cargar dumps de Odoo.
  - Firma con mouse: componente st.components.v2 (canvas) que devuelve los TRAZOS
    (vectores), y estampar_firma() los dibuja sobre la pagina del PDF con pypdf.
    Vector => nitida a cualquier zoom y con fondo transparente (no tapa el texto).
    El firmado es una COPIA nueva (firmado_de -> original); el original no se toca.

Borrado = logico (eliminado = TRUE); el objeto en Storage se conserva.
"""
from __future__ import annotations

import hashlib
import io
import re
import unicodedata
import uuid
from datetime import datetime

import pandas as pd
import streamlit as st
from sqlalchemy import text

from components.common import execute_write, execute_write_returning, get_engine, _clean_params
from components import storage as S

API_VERSION = 2


def load_query(sql: str, params: dict | None = None) -> pd.DataFrame:
    """Lectura SIN cache. common.load_query cachea 5 minutos (bien para silver, que
    cambia 1 vez al dia), pero aqui una carpeta o archivo recien creado tiene que
    verse en el acto (2026-11-09: la carpeta 'Prueba' no aparecia)."""
    with get_engine().connect() as conn:
        return pd.read_sql_query(text(sql), conn, params=_clean_params(params or {}))


# =============================================================================
# Tablas (self-healing, como Facturas)
# =============================================================================
@st.cache_resource
def ensure_tables() -> bool:
    execute_write("""
        CREATE TABLE IF NOT EXISTS operational.doc_carpetas (
            carpeta_id      bigserial PRIMARY KEY,
            parent_id       bigint REFERENCES operational.doc_carpetas(carpeta_id),
            nombre          text NOT NULL,
            sede_nombre     text,               -- NULL = todas las sedes
            odoo_folder_id  integer UNIQUE,
            created_by      text,
            created_at      timestamptz NOT NULL DEFAULT now()
        );
        CREATE UNIQUE INDEX IF NOT EXISTS doc_carpetas_nombre_uq
            ON operational.doc_carpetas (COALESCE(parent_id, 0), lower(nombre));
        CREATE TABLE IF NOT EXISTS operational.documentos (
            documento_id        bigserial PRIMARY KEY,
            carpeta_id          bigint NOT NULL REFERENCES operational.doc_carpetas(carpeta_id),
            nombre              text NOT NULL,
            storage_path        text NOT NULL UNIQUE,
            mime_type           text,
            tamano_bytes        bigint,
            sha256              text,
            descripcion         text,
            sede_nombre         text,
            origen              text NOT NULL DEFAULT 'dashboard',   -- dashboard | odoo
            odoo_attachment_id  integer UNIQUE,
            firmado_de          bigint REFERENCES operational.documentos(documento_id),
            firmado_por         text,
            firmado_at          timestamptz,
            subido_por          text,
            subido_at           timestamptz NOT NULL DEFAULT now(),
            eliminado           boolean NOT NULL DEFAULT FALSE,
            eliminado_por       text,
            eliminado_at        timestamptz
        );
        CREATE INDEX IF NOT EXISTS documentos_carpeta_idx
            ON operational.documentos (carpeta_id) WHERE NOT eliminado;
    """, {})
    S.ensure_bucket()
    return True


# =============================================================================
# Carpetas
# =============================================================================
def carpetas():
    return load_query("""
        SELECT carpeta_id, parent_id, nombre, sede_nombre
        FROM operational.doc_carpetas ORDER BY lower(nombre)
    """)


def rutas_carpetas(df) -> dict[int, str]:
    """carpeta_id -> 'Contabilidad / RNT / 2026' (para el selector)."""
    by_id = {int(r.carpeta_id): r for r in df.itertuples()}
    out = {}
    for cid in by_id:
        partes, cur, vistos = [], by_id.get(cid), set()
        while cur is not None and int(cur.carpeta_id) not in vistos:
            vistos.add(int(cur.carpeta_id))
            partes.append(cur.nombre)
            cur = by_id.get(int(cur.parent_id)) if cur.parent_id == cur.parent_id and cur.parent_id is not None else None
        out[cid] = " / ".join(reversed(partes))
    return dict(sorted(out.items(), key=lambda kv: kv[1].lower()))


def crear_carpeta(nombre: str, parent_id: int | None, usuario: str) -> None:
    execute_write("""
        INSERT INTO operational.doc_carpetas (parent_id, nombre, created_by)
        VALUES (:p, :n, :u)
    """, {"p": parent_id, "n": nombre.strip(), "u": usuario})


# =============================================================================
# Documentos
# =============================================================================
def _slug(nombre: str) -> str:
    """Nombre seguro para la llave de Storage (sin tildes, espacios ni simbolos)."""
    s = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("._") or "archivo"
    return s[:120]


def documentos(carpeta_id: int):
    return load_query("""
        SELECT d.documento_id, d.nombre, d.mime_type, d.tamano_bytes, d.storage_path,
               d.subido_por, d.subido_at, d.firmado_de, d.firmado_por, d.firmado_at,
               d.descripcion, d.origen
        FROM operational.documentos d
        WHERE d.carpeta_id = :c AND NOT d.eliminado
        ORDER BY d.subido_at DESC
    """, {"c": int(carpeta_id)})


def subir(carpeta_id: int, nombre: str, data: bytes, mime: str, usuario: str,
          descripcion: str = "", firmado_de: int | None = None) -> int:
    """Sube el binario y registra la fila. Si el INSERT falla, borra el objeto."""
    path = f"{int(carpeta_id)}/{uuid.uuid4().hex}_{_slug(nombre)}"
    S.upload(path, data, mime)
    try:
        return execute_write_returning("""
            INSERT INTO operational.documentos
                (carpeta_id, nombre, storage_path, mime_type, tamano_bytes, sha256,
                 descripcion, subido_por, firmado_de, firmado_por, firmado_at)
            VALUES (:c, :n, :p, :m, :t, :h, :d, :u, :f,
                    CASE WHEN :f IS NULL THEN NULL ELSE :u END,
                    CASE WHEN :f IS NULL THEN NULL ELSE now() END)
            RETURNING documento_id
        """, {"c": int(carpeta_id), "n": nombre, "p": path, "m": mime, "t": len(data),
              "h": hashlib.sha256(data).hexdigest(), "d": descripcion or None,
              "u": usuario, "f": firmado_de})
    except Exception:
        try:
            S.delete([path])
        finally:
            raise


def eliminar(documento_id: int, usuario: str) -> None:
    execute_write("""
        UPDATE operational.documentos
        SET eliminado = TRUE, eliminado_por = :u, eliminado_at = now()
        WHERE documento_id = :id
    """, {"id": int(documento_id), "u": usuario})


# =============================================================================
# Firma con mouse (componente v2: canvas -> trazos)
# =============================================================================
_FIRMA_HTML = """
<div class="firma">
  <canvas width="600" height="200"></canvas>
  <div class="barra">
    <button class="limpiar" type="button">Limpiar</button>
    <button class="usar" type="button">Usar esta firma</button>
    <span class="estado"></span>
  </div>
</div>
"""
_FIRMA_CSS = """
.firma { font-family: sans-serif; }
canvas { border: 1px dashed #999; border-radius: 6px; background: #fff;
         touch-action: none; cursor: crosshair; width: 100%; max-width: 600px;
         aspect-ratio: 3 / 1; display: block; }
.barra { margin-top: 6px; display: flex; gap: 8px; align-items: center; }
button { padding: 6px 14px; border-radius: 6px; border: 1px solid #bbb;
         background: #f5f5f5; cursor: pointer; }
button.usar { background: #ff5f00; color: #fff; border-color: #ff5f00; }
.estado { font-size: 13px; color: #555; }
"""
_FIRMA_JS = """
export default function(component) {
  const { parentElement, setTriggerValue } = component;
  const cv = parentElement.querySelector('canvas');
  if (cv.dataset.listo) return;          // re-render de Streamlit: no duplicar handlers
  cv.dataset.listo = '1';
  const ctx = cv.getContext('2d');
  ctx.lineWidth = 2.2; ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.strokeStyle = '#0b2a6f';
  const estado = parentElement.querySelector('.estado');
  let trazos = [], actual = null;
  const punto = (e) => {
    const r = cv.getBoundingClientRect();
    return [ (e.clientX - r.left) * cv.width / r.width,
             (e.clientY - r.top) * cv.height / r.height ];
  };
  cv.addEventListener('pointerdown', (e) => {
    cv.setPointerCapture(e.pointerId);
    actual = [punto(e)]; trazos.push(actual);
    ctx.beginPath(); ctx.moveTo(...actual[0]);
  });
  cv.addEventListener('pointermove', (e) => {
    if (!actual) return;
    const p = punto(e); actual.push(p); ctx.lineTo(...p); ctx.stroke();
  });
  const fin = () => { actual = null; };
  cv.addEventListener('pointerup', fin); cv.addEventListener('pointercancel', fin);
  parentElement.querySelector('.limpiar').onclick = () => {
    trazos = []; ctx.clearRect(0, 0, cv.width, cv.height); estado.textContent = '';
    setTriggerValue('firma', null);
  };
  parentElement.querySelector('.usar').onclick = () => {
    const t = trazos.filter(s => s.length > 1)
                    .map(s => s.map(([x, y]) => [Math.round(x * 10) / 10, Math.round(y * 10) / 10]));
    if (!t.length) { estado.textContent = 'Dibuja la firma primero.'; return; }
    setTriggerValue('firma', { w: cv.width, h: cv.height, trazos: t, png: cv.toDataURL('image/png') });
    estado.textContent = 'Firma lista.';
  };
}
"""

_firma_component = st.components.v2.component(
    "trust_firma_mouse", html=_FIRMA_HTML, css=_FIRMA_CSS, js=_FIRMA_JS)


def panel_firma(key: str):
    """Dibuja el panel. Devuelve el ultimo dict {w,h,trazos,png} confirmado o None.
    Se guarda en session_state porque el trigger solo vive en el rerun del clic."""
    res = _firma_component(key=key, on_firma_change=lambda: None)
    try:
        val = res.firma
        presente = True
    except (AttributeError, KeyError):
        val, presente = None, False
    if presente and val is not None:
        st.session_state[f"{key}__firma"] = val
    elif presente and val is None and f"{key}__firma__visto" in st.session_state:
        # 'Limpiar' manda None explicito: se descarta la firma guardada
        st.session_state.pop(f"{key}__firma", None)
    st.session_state[f"{key}__firma__visto"] = True
    return st.session_state.get(f"{key}__firma")


def limpiar_firma(key: str) -> None:
    st.session_state.pop(f"{key}__firma", None)


# =============================================================================
# Estampar la firma (vectorial) en un PDF
# =============================================================================
def _pdf_text(s: str) -> bytes:
    b = s.encode("cp1252", "replace")
    return b.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def info_pdf(data: bytes) -> list[tuple[float, float]]:
    """(ancho, alto) en puntos de cada pagina, ya considerando la rotacion."""
    from pypdf import PdfReader
    out = []
    for p in PdfReader(io.BytesIO(data)).pages:
        w, h = float(p.mediabox.width), float(p.mediabox.height)
        if int(p.get("/Rotate", 0) or 0) % 180:
            w, h = h, w
        out.append((w, h))
    return out


def estampar_firma(data: bytes, firma: dict, pagina: int, x_pct: float, y_pct: float,
                   ancho_pct: float, leyenda: str = "") -> bytes:
    """Dibuja los trazos sobre la `pagina` (0-based). x_pct/y_pct = esquina inferior
    izquierda de la firma en % de la pagina (y medido desde ABAJO); ancho_pct = ancho
    de la firma en % del ancho de la pagina. `leyenda` va debajo, en letra pequena."""
    from pypdf import PdfReader, PdfWriter, Transformation
    from pypdf.generic import (DecodedStreamObject, DictionaryObject, NameObject)

    reader = PdfReader(io.BytesIO(data))
    writer = PdfWriter(clone_from=reader)
    page = writer.pages[pagina]
    rot = int(page.get("/Rotate", 0) or 0) % 360
    mb = page.mediabox
    W, H = float(mb.width), float(mb.height)
    vw, vh = (H, W) if rot % 180 else (W, H)      # tamano como se VE la pagina

    pts = [p for s in firma["trazos"] for p in s]
    minx, maxx = min(p[0] for p in pts), max(p[0] for p in pts)
    miny, maxy = min(p[1] for p in pts), max(p[1] for p in pts)
    bw, bh = max(maxx - minx, 1.0), max(maxy - miny, 1.0)
    ancho = vw * ancho_pct / 100.0
    esc = ancho / bw
    x0, y0 = vw * x_pct / 100.0, vh * y_pct / 100.0
    lw = max(0.6, min(2.0, 2.2 * esc))

    ops = [b"q", b"0.043 0.165 0.435 RG", f"{lw:.2f} w 1 J 1 j".encode()]
    for s in firma["trazos"]:
        seg = []
        for i, (x, y) in enumerate(s):
            px = x0 + (x - minx) * esc
            py = y0 + (maxy - y) * esc            # canvas: y hacia abajo; PDF: hacia arriba
            seg.append(f"{px:.2f} {py:.2f} {'m' if i == 0 else 'l'}".encode())
        ops += seg + [b"S"]
    ops.append(b"Q")
    if leyenda:
        ops += [b"BT /FTrustF 7 Tf 0.25 0.25 0.25 rg",
                f"{x0:.2f} {max(y0 - 9, 2):.2f} Td".encode(),
                b"(" + _pdf_text(leyenda) + b") Tj ET"]

    # La hoja de la firma se arma en coordenadas "como se ve" y se rota para calzar
    # con el /Rotate de la pagina destino.
    w2 = PdfWriter()
    ov = w2.add_blank_page(width=vw, height=vh)
    stream = DecodedStreamObject()
    stream.set_data(b"\n".join(ops))
    ov[NameObject("/Contents")] = w2._add_object(stream)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                             NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica"),
                             NameObject("/Encoding"): NameObject("/WinAnsiEncoding")})
    ov[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/FTrustF"): font})})
    buf = io.BytesIO()
    w2.write(buf)
    ov_page = PdfReader(io.BytesIO(buf.getvalue())).pages[0]

    ox, oy = float(mb.left), float(mb.bottom)
    if rot == 0:
        t = Transformation().translate(ox, oy)
    elif rot == 90:      # se ve girada 90 horario: (x,y)visto -> (y, ... )
        t = Transformation().rotate(90).translate(ox + W, oy)
    elif rot == 180:
        t = Transformation().rotate(180).translate(ox + W, oy + H)
    else:                # 270
        t = Transformation().rotate(270).translate(ox, oy + H)
    page.merge_transformed_page(ov_page, t)

    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def nombre_firmado(nombre: str) -> str:
    base, dot, ext = nombre.rpartition(".")
    stamp = datetime.now().strftime("%Y%m%d")
    return f"{base}_firmado_{stamp}.{ext}" if dot else f"{nombre}_firmado_{stamp}.pdf"
