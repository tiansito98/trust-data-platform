"""
Expedientes de contrato firmados (sobre components/documentos.py + Supabase Storage).

EL CONTRATO ES LA LLAVE (2026-11-11): es unico para siempre y a mitad de renta le pueden
cambiar el carro, asi que las carpetas van por contrato, no por placa. El asesor NO digita
la placa (2026-11-11): las placas salen del sistema (todos los tramos del contrato).

Flujo:
  1. El asesor digita el CONTRATO, elige el TRAMITE y sube SOLO el PDF del contrato.
     - RENTA: contrato + addendum + informacion de renta (ES o EN, segun el cliente).
     - SOLO_CONTRATO: solo el contrato (no todo lo que se firma lleva los anexos).
  2. Los anexos salen de PLANTILLAS fijas (operational.doc_plantillas: una activa por
     tipo x idioma, versionadas). Cada plantilla trae sus CAMPOS en posiciones exactas
     (firma, nombre del cliente, numero de contrato, fecha), p.ej. el addendum lleva
     "agreement number", "Print Name", "Signature" y "Date".
  3. El cliente firma UNA vez; la firma (y su nombre) quedan en todos los documentos.
     Vista previa de todos -> guardar.
  4. Carpeta  Contratos / <CONTRATO>  (Storage: contratos/<CONTRATO>/...) y nombres
     <CONTRATO>_<TIPO>_<AAAAMMDD>.pdf. Ademas de lo firmado, la carpeta guarda
     ADJUNTOS que no se firman: comprobante de pago (voucher escaneado) y factura
     electronica (PDF o imagen; mas adelante se leen con IA para quitar la digitacion
     de Facturas). Se pueden cargar despues, pero la validacion los EXIGE.
  5. Validacion (como Facturas) contra silver: faltan firmados (segun el tramite) /
     falta comprobante o factura / pendiente / al dia; y contratos del sistema sin
     expediente desde FECHA_INICIO.

Re-firmar un tipo reemplaza al anterior (el viejo queda eliminado = TRUE y se ve como
"version anterior"). QUIEN hizo el proceso queda en la base (usuario del dashboard);
quien FIRMO (el cliente) queda en doc_contratos.firmante_nombre y en el addendum.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import date, datetime

import pandas as pd
import streamlit as st

from components import documentos as D
from components import storage as S
from components.common import execute_write, execute_write_returning, get_engine
from sqlalchemy import text

API_VERSION = 7

# Los que se FIRMAN
TIPOS = {
    "CONTRATO": "Contrato",
    "ADENDUM": "Addendum",
    "INFO_GENERAL": "Información de renta",
}
# Los que solo se GUARDAN (no se firman). Se pueden cargar despues, pero la validacion
# los exige en todo expediente (ADJUNTOS_REQUERIDOS).
ADJUNTOS = {
    "COMPROBANTE_PAGO": "Comprobante de pago",
    "FACTURA_ELECTRONICA": "Factura electrónica",
}
ADJUNTOS_REQUERIDOS = list(ADJUNTOS)
EXT_ADJUNTO = {"pdf": "application/pdf", "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png"}
# Como se llama cada tipo en el NOMBRE del archivo
TIPO_ARCHIVO = {"CONTRATO": "CONTRATO", "ADENDUM": "ADDENDUM", "INFO_GENERAL": "INFO_RENTA",
                "COMPROBANTE_PAGO": "COMPROBANTE_PAGO", "FACTURA_ELECTRONICA": "FACTURA_ELECTRONICA"}
TIPOS_PLANTILLA = ("ADENDUM", "INFO_GENERAL")
IDIOMAS = {"ES": "Español", "EN": "English"}
TRAMITES = {
    "RENTA": {"nombre": "Renta (contrato + addendum + información de renta)",
              "requeridos": ["CONTRATO", "ADENDUM", "INFO_GENERAL"]},
    "SOLO_CONTRATO": {"nombre": "Solo el contrato", "requeridos": ["CONTRATO"]},
}
CARPETA_RAIZ = "Contratos"

# Desde cuando se exige expediente: los contratos anteriores no salen como
# "sin documentos" en la validacion. AJUSTAR al dia que arranque el uso real.
FECHA_INICIO = date(2026, 11, 9)

_RE_PLACA = re.compile(r"^[A-Z]{3}[0-9]{3}$")      # carros en Colombia: ABC123
_RE_CONTRATO = re.compile(r"^[0-9]{10}$")          # contratos Sixt: 10 digitos


def etiqueta(tipo: str, idioma: str | None = None) -> str:
    t = TIPOS.get(tipo) or ADJUNTOS.get(tipo) or \
        ("Contrato sin firma (original)" if tipo == "CONTRATO_SIN_FIRMA" else tipo)
    return f"{t} ({IDIOMAS[idioma]})" if idioma in IDIOMAS else t


# =============================================================================
# Formatos
# =============================================================================
def normalizar_placa(txt: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (txt or "").upper())


def placa_valida(p: str) -> bool:
    return bool(_RE_PLACA.match(p or ""))


def contrato_valido(c: str) -> bool:
    return bool(_RE_CONTRATO.match((c or "").strip()))


def nombre_archivo(contrato: int, tipo: str, fecha: date, idioma: str | None = None,
                   firmado: bool = True, ext: str = "pdf") -> str:
    """9524178852_ADDENDUM_20261110.pdf · ..._INFO_RENTA_ES_... · ..._CONTRATO_SIN_FIRMA_...
    · 9524178852_COMPROBANTE_PAGO_20261110.jpg"""
    t = TIPO_ARCHIVO.get(tipo, tipo) + (f"_{idioma}" if idioma else "") + ("" if firmado else "_SIN_FIRMA")
    return f"{int(contrato)}_{t}_{fecha:%Y%m%d}.{ext.lower().lstrip('.')}"


def ext_de(nombre: str) -> str:
    e = (nombre or "").rsplit(".", 1)[-1].lower()
    return "jpg" if e == "jpeg" else e


# =============================================================================
# Tablas
# =============================================================================
@st.cache_resource
def ensure_tables() -> bool:
    D.ensure_tables()
    execute_write("""
        CREATE TABLE IF NOT EXISTS operational.doc_plantillas (
            plantilla_id   bigserial PRIMARY KEY,
            tipo           text NOT NULL CHECK (tipo IN ('ADENDUM', 'INFO_GENERAL')),
            idioma         text CHECK (idioma IN ('ES', 'EN')),
            version        integer NOT NULL,
            nombre         text NOT NULL,
            storage_path   text NOT NULL UNIQUE,
            campos         jsonb NOT NULL DEFAULT '[]'::jsonb,   -- ver estampar_campos
            activa         boolean NOT NULL DEFAULT TRUE,
            subido_por     text,
            subido_at      timestamptz NOT NULL DEFAULT now()
        );
        CREATE UNIQUE INDEX IF NOT EXISTS doc_plantillas_version_uq
            ON operational.doc_plantillas (tipo, COALESCE(idioma, ''), version);
        CREATE UNIQUE INDEX IF NOT EXISTS doc_plantillas_activa_uq2
            ON operational.doc_plantillas (tipo, COALESCE(idioma, '')) WHERE activa;
        CREATE TABLE IF NOT EXISTS operational.doc_contratos (
            contrato        bigint PRIMARY KEY,
            placa           text,
            sede_nombre     text,
            creado_por      text,
            creado_at       timestamptz NOT NULL DEFAULT now(),
            actualizado_por text,
            actualizado_at  timestamptz
        );
        ALTER TABLE operational.doc_contratos ADD COLUMN IF NOT EXISTS tramite text;
        ALTER TABLE operational.doc_contratos ADD COLUMN IF NOT EXISTS requeridos text[];
        ALTER TABLE operational.doc_contratos ADD COLUMN IF NOT EXISTS firmante_nombre text;
        ALTER TABLE operational.doc_contratos ADD COLUMN IF NOT EXISTS idioma text;
        ALTER TABLE operational.doc_contratos ADD COLUMN IF NOT EXISTS carpeta_id bigint;
        ALTER TABLE operational.doc_contratos ADD COLUMN IF NOT EXISTS firmado_at timestamptz;
        -- 2026-11-11: el asesor ya no digita la placa; se llena con las del sistema si ya llego
        ALTER TABLE operational.doc_contratos ALTER COLUMN placa DROP NOT NULL;
        CREATE INDEX IF NOT EXISTS doc_contratos_placa_idx ON operational.doc_contratos (placa);
        -- un solo documento VIGENTE por (contrato, tipo); re-firmar marca el viejo eliminado
        CREATE UNIQUE INDEX IF NOT EXISTS documentos_contrato_tipo_uq
            ON operational.documentos (contrato, tipo_documento)
            WHERE NOT eliminado AND tipo_documento IS NOT NULL AND contrato IS NOT NULL;
    """, {})
    _crear_vista()
    return True


def _crear_vista() -> None:
    """operational.vw_documentos_contratos: indice para consultar desde el SQL Editor,
    1 fila por documento, con enlace a su carpeta en el panel de Supabase (Storage).
    VIEW de verdad (no tabla): siempre al dia."""
    ref = S.project_ref()
    # DROP + CREATE: CREATE OR REPLACE no deja reordenar columnas (contrato va primero)
    execute_write(f"""
        DROP VIEW IF EXISTS operational.vw_documentos_contratos;
        CREATE VIEW operational.vw_documentos_contratos AS
        SELECT e.contrato,
               e.placa                               AS placas_al_firmar,
               (COALESCE(e.firmado_at, e.creado_at) AT TIME ZONE 'America/Bogota') AS firmado_el,
               e.tramite,
               e.firmante_nombre                     AS cliente,
               e.creado_por                          AS usuario,
               d.tipo_documento,
               d.nombre                              AS archivo,
               NOT d.eliminado                       AS vigente,
               (d.subido_at AT TIME ZONE 'America/Bogota') AS cargado_el,
               d.firmado_por,
               d.tamano_bytes,
               d.storage_path,
               'https://supabase.com/dashboard/project/{ref}/storage/buckets/documentos?path='
                   || replace(regexp_replace(d.storage_path, '/[^/]*$', ''), '/', chr(37) || '2F') AS link_carpeta,
               d.documento_id,
               e.sede_nombre
        FROM operational.doc_contratos e
        JOIN operational.documentos d ON d.contrato = e.contrato AND d.tipo_documento IS NOT NULL
    """, {})


# =============================================================================
# Plantillas
# =============================================================================
def _campos(v) -> list[dict]:
    if isinstance(v, str):
        return json.loads(v or "[]")
    return list(v or [])


def plantillas_activas() -> pd.DataFrame:
    df = D.load_query("""
        SELECT plantilla_id, tipo, idioma, version, nombre, storage_path, campos, subido_por, subido_at
        FROM operational.doc_plantillas WHERE activa ORDER BY tipo, idioma
    """)
    df["campos"] = df["campos"].map(_campos)
    return df


def historial_plantillas() -> pd.DataFrame:
    return D.load_query("""
        SELECT plantilla_id, tipo, idioma, version, nombre, activa, subido_por, subido_at
        FROM operational.doc_plantillas ORDER BY tipo, idioma, version DESC
    """)


def subir_plantilla(tipo: str, idioma: str | None, nombre: str, data: bytes, usuario: str,
                    campos: list[dict] | None = None) -> int:
    """Nueva VERSION (la anterior queda inactiva, no se borra: los expedientes viejos
    siguen apuntando a la version con la que se firmaron). Sin `campos`, hereda los de
    la version anterior, o una firma abajo a la derecha de la ultima pagina."""
    assert tipo in TIPOS_PLANTILLA and idioma in (None, *IDIOMAS)
    n = len(D.info_pdf(data))   # valida que sea un PDF legible
    if campos is None:
        prev = D.load_query("""
            SELECT campos FROM operational.doc_plantillas
            WHERE tipo = :t AND COALESCE(idioma, '') = COALESCE(:i, '') ORDER BY version DESC LIMIT 1
        """, {"t": tipo, "i": idioma})
        campos = _campos(prev.iloc[0, 0]) if not prev.empty else [
            {"tipo": "firma", "pagina": n, "x": 64, "y": 8, "ancho": 28, "alto": 7, "leyenda": True}]
    path = f"plantillas/{tipo}{'_' + idioma if idioma else ''}/" \
           f"{pd.Timestamp.now(tz='America/Bogota'):%Y%m%d_%H%M%S}_{D._slug(nombre)}"
    S.upload(path, data, "application/pdf")
    try:
        execute_write("""
            UPDATE operational.doc_plantillas SET activa = FALSE
            WHERE tipo = :t AND COALESCE(idioma, '') = COALESCE(:i, '') AND activa
        """, {"t": tipo, "i": idioma})
        return execute_write_returning("""
            INSERT INTO operational.doc_plantillas (tipo, idioma, version, nombre, storage_path, campos, subido_por)
            SELECT :t, :i, COALESCE(MAX(version), 0) + 1, :n, :p, CAST(:c AS jsonb), :u
            FROM operational.doc_plantillas WHERE tipo = :t AND COALESCE(idioma, '') = COALESCE(:i, '')
            RETURNING plantilla_id
        """, {"t": tipo, "i": idioma, "n": nombre, "p": path, "c": json.dumps(campos), "u": usuario})
    except Exception:
        S.delete([path])
        raise


def actualizar_campos(plantilla_id: int, campos: list[dict]) -> None:
    execute_write("UPDATE operational.doc_plantillas SET campos = CAST(:c AS jsonb) WHERE plantilla_id = :id",
                  {"id": int(plantilla_id), "c": json.dumps(campos)})


def campos_para_estampar(campos: list[dict], n_paginas: int, valores: dict, leyenda: str) -> list[dict]:
    """Campos de la plantilla (pagina 1-based, 'valor': nombre|contrato|fecha) -> los de
    estampar_campos (pagina 0-based, texto ya resuelto)."""
    out = []
    for c in campos:
        pg = min(max(int(c.get("pagina") or n_paginas), 1), n_paginas) - 1
        if c["tipo"] == "firma":
            out.append({"tipo": "firma", "pagina": pg, "x": c["x"], "y": c["y"], "ancho": c["ancho"],
                        "alto": c.get("alto"), "leyenda": leyenda if c.get("leyenda") else ""})
        else:
            out.append({"tipo": "texto", "pagina": pg, "x": c["x"], "y": c["y"], "size": c.get("size", 9),
                        "texto": valores.get(c.get("valor"), "")})
    return out


# =============================================================================
# Carpetas automaticas  Contratos / CONTRATO
# =============================================================================
def _carpeta(nombre: str, parent_id: int | None, usuario: str) -> int:
    execute_write("""
        INSERT INTO operational.doc_carpetas (parent_id, nombre, created_by)
        VALUES (:p, :n, :u) ON CONFLICT DO NOTHING
    """, {"p": parent_id, "n": nombre, "u": usuario})
    return int(D.load_query("""
        SELECT carpeta_id FROM operational.doc_carpetas
        WHERE COALESCE(parent_id, 0) = COALESCE(CAST(:p AS bigint), 0) AND lower(nombre) = lower(:n)
    """, {"p": parent_id, "n": nombre}).iloc[0, 0])


def carpeta_contrato(contrato: int, usuario: str) -> int:
    raiz = _carpeta(CARPETA_RAIZ, None, usuario)
    return _carpeta(str(int(contrato)), raiz, usuario)


def _storage_dir(contrato: int) -> str:
    """Misma estructura que el dashboard: contratos/<CONTRATO>"""
    return f"contratos/{int(contrato)}"


def _objeto(nombre: str) -> str:
    """Nombre del objeto en Storage: el nombre limpio + hora + 4 hex (unico aunque se
    re-firme el mismo dia o dos personas guarden en el mismo segundo)."""
    base, _, ext = nombre.rpartition(".")
    return f"{base}_{pd.Timestamp.now(tz='America/Bogota'):%H%M%S}_{uuid.uuid4().hex[:4]}.{ext}"


# =============================================================================
# Expedientes
# =============================================================================
def expediente(contrato: int) -> dict | None:
    df = D.load_query("SELECT * FROM operational.doc_contratos WHERE contrato = :c", {"c": int(contrato)})
    return None if df.empty else df.iloc[0].to_dict()


def expediente_de_carpeta(carpeta_id: int) -> dict | None:
    """El expediente cuya carpeta es esta (para mostrarlo en Archivos generales)."""
    df = D.load_query("SELECT * FROM operational.doc_contratos WHERE carpeta_id = :c", {"c": int(carpeta_id)})
    return None if df.empty else df.iloc[0].to_dict()


def documentos_contrato(contrato: int, vigentes: bool = True) -> pd.DataFrame:
    """Documentos del contrato. vigentes=False -> las versiones reemplazadas."""
    return D.load_query(f"""
        SELECT d.documento_id, d.tipo_documento, d.nombre, d.storage_path, d.mime_type,
               d.tamano_bytes, d.subido_por, d.subido_at, d.firmado_de, d.firmado_por,
               d.firmado_at, d.contrato, d.placas, d.firma_pagina, d.carpeta_id,
               d.eliminado_at, d.eliminado_por, p.version AS plantilla_version, p.idioma
        FROM operational.documentos d
        LEFT JOIN operational.doc_plantillas p ON p.plantilla_id = d.plantilla_id
        WHERE d.contrato = :c AND d.tipo_documento IS NOT NULL
          AND {'NOT' if vigentes else ''} d.eliminado
        ORDER BY CASE d.tipo_documento WHEN 'CONTRATO' THEN 1 WHEN 'CONTRATO_SIN_FIRMA' THEN 2
                      WHEN 'ADENDUM' THEN 3 WHEN 'INFO_GENERAL' THEN 4 WHEN 'COMPROBANTE_PAGO' THEN 5
                      WHEN 'FACTURA_ELECTRONICA' THEN 6 ELSE 7 END, d.subido_at DESC
    """, {"c": int(contrato)})


def plantillas_del_tramite(tramite: str, idioma: str, pla: pd.DataFrame) -> pd.DataFrame:
    """Las plantillas que lleva el tramite: addendum (su idioma o el unico que haya)
    + informacion de renta en el idioma del cliente."""
    req = TRAMITES[tramite]["requeridos"]
    filas = []
    for tipo in TIPOS_PLANTILLA:
        if tipo not in req:
            continue
        cand = pla[pla["tipo"] == tipo]
        exacta = cand[cand["idioma"] == idioma]
        elegida = exacta if not exacta.empty else cand[cand["idioma"].isna()]
        if elegida.empty and not cand.empty and tipo == "ADENDUM":
            elegida = cand.head(1)          # el addendum solo existe en ingles
        if not elegida.empty:
            filas.append(elegida.iloc[0])
    return pd.DataFrame(filas)


def preparar(contrato_pdf: bytes, firma: dict, pos_contrato: dict, valores: dict, leyenda: str,
             plantillas: pd.DataFrame, bytes_de) -> list[dict]:
    """Estampa la firma en el contrato y en cada plantilla. No guarda nada.
    pos_contrato = {pagina 0-based, x, y, ancho}. valores = {nombre, contrato, fecha}.
    Devuelve [{tipo, idioma, firmado, original, pagina (0-based, la de la firma), plantilla_id}]."""
    out = [{
        "tipo": "CONTRATO", "idioma": None, "original": contrato_pdf, "plantilla_id": None,
        "pagina": pos_contrato["pagina"],
        "firmado": D.estampar_campos(contrato_pdf, firma, [{
            "tipo": "firma", "pagina": pos_contrato["pagina"], "x": pos_contrato["x"], "y": pos_contrato["y"],
            "ancho": pos_contrato["ancho"], "leyenda": leyenda}]),
    }]
    for p in plantillas.itertuples():
        data = bytes_de(p.storage_path)
        n = len(D.info_pdf(data))
        campos = campos_para_estampar(p.campos, n, valores, leyenda)
        pg_firma = next((c["pagina"] for c in campos if c["tipo"] == "firma"), n - 1)
        out.append({"tipo": p.tipo, "idioma": p.idioma if isinstance(p.idioma, str) else None,
                    "original": data, "plantilla_id": int(p.plantilla_id), "pagina": pg_firma,
                    "firmado": D.estampar_campos(data, firma, campos)})
    return out


def adjunto(tipo: str, nombre_original: str, data: bytes) -> dict:
    """Valida un adjunto (comprobante / factura) y lo deja listo para guardar()."""
    assert tipo in ADJUNTOS, tipo
    ext = ext_de(nombre_original)
    if ext not in EXT_ADJUNTO:
        raise ValueError(f"{ADJUNTOS[tipo]}: solo PDF, JPG o PNG.")
    if ext == "pdf":
        D.info_pdf(data)        # que sea un PDF legible
    return {"tipo": tipo, "data": data, "mime": EXT_ADJUNTO[ext], "ext": ext}


def _subir_y_registrar(contrato: int, filas: list[dict], usuario: str, upsert_expediente=None) -> dict:
    """Nucleo ATOMICO (pensado para ~7 personas a la vez):
      1. sube todos los archivos a Storage (rutas unicas, no chocan entre usuarios);
      2. registra TODO en UNA transaccion con un candado por contrato
         (pg_advisory_xact_lock): si dos personas guardan el mismo contrato a la vez,
         la segunda espera a la primera y luego reemplaza limpio; nunca queda medio
         expediente ni dos versiones vigentes del mismo tipo;
      3. si la transaccion falla, borra lo que subio en el paso 1.
    filas = [{tipo, data, mime, nombre, firmado, plantilla_id, pagina}].
    upsert_expediente(conn, carpeta_id) escribe doc_contratos dentro de la transaccion;
    sin el, el expediente TIENE que existir. Devuelve {tipo: documento_id}."""
    contrato = int(contrato)
    if upsert_expediente is None and expediente(contrato) is None:
        raise ValueError(f"El contrato {contrato} no tiene expediente.")
    carpeta = carpeta_contrato(contrato, usuario)
    info = D.info_contrato(contrato) or {"placas": [], "sede": None}
    subidos = []
    try:
        for f in filas:
            f["path"] = f"{_storage_dir(contrato)}/{_objeto(f['nombre'])}"
            S.upload(f["path"], f["data"], f["mime"])
            subidos.append(f["path"])

        ids = {}
        with get_engine().begin() as conn:
            conn.execute(text("SET LOCAL search_path TO operational, public"))
            conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": contrato})
            if upsert_expediente is not None:
                upsert_expediente(conn, carpeta)
            fila_e = conn.execute(text("SELECT sede_nombre FROM operational.doc_contratos WHERE contrato = :c"),
                                  {"c": contrato}).first()
            if fila_e is None:
                raise ValueError(f"El contrato {contrato} no tiene expediente.")
            sede = fila_e[0]
            conn.execute(text("""
                UPDATE operational.documentos
                SET eliminado = TRUE, eliminado_por = :u, eliminado_at = now()
                WHERE contrato = :c AND tipo_documento = ANY(:t) AND NOT eliminado
            """), {"c": contrato, "t": sorted({f["tipo"] for f in filas}), "u": usuario})
            sin_firma_id = None
            for f in filas:
                nid = conn.execute(text("""
                    INSERT INTO operational.documentos
                        (carpeta_id, nombre, storage_path, mime_type, tamano_bytes, sha256, subido_por,
                         firmado_de, firmado_por, firmado_at, contrato, placas, sede_nombre,
                         firma_pagina, tipo_documento, plantilla_id)
                    VALUES (:cp, :n, :p, :m, :t, :h, :u,
                            :fd, :fp, CASE WHEN :fp IS NULL THEN NULL ELSE now() END,
                            :c, :pl, :s, :pg, :td, :pi)
                    RETURNING documento_id
                """), {"cp": carpeta, "n": f["nombre"], "p": f["path"], "m": f["mime"], "t": len(f["data"]),
                       "h": hashlib.sha256(f["data"]).hexdigest(), "u": usuario,
                       "fd": sin_firma_id if f["tipo"] == "CONTRATO" else None,
                       "fp": usuario if f.get("firmado") else None, "c": contrato,
                       "pl": list(info.get("placas") or []), "s": info.get("sede") or sede,
                       "pg": f.get("pagina"), "td": f["tipo"], "pi": f.get("plantilla_id")}).scalar()
                if f["tipo"] == "CONTRATO_SIN_FIRMA":
                    sin_firma_id = nid
                else:
                    ids[f["tipo"]] = nid
        return ids
    except Exception:
        if subidos:
            try:
                S.delete(subidos)
            except Exception:  # noqa: BLE001
                pass
        raise


def guardar(contrato: int, preparados: list[dict], usuario: str, tramite: str,
            firmante: str = "", idioma: str | None = None, sede: str | None = None,
            adjuntos: list[dict] | None = None) -> dict:
    """Guarda el expediente en Contratos/<CONTRATO>: contrato SIN firmar (traza) + los
    firmados + los adjuntos opcionales (comprobante de pago / factura electronica, de
    adjunto()). Re-firmar reemplaza (lo viejo queda como version anterior). La placa no
    se digita: se guardan las del sistema si el contrato ya llego. Devuelve {tipo: documento_id}."""
    contrato = int(contrato)
    hoy = pd.Timestamp.now(tz="America/Bogota").date()
    info = D.info_contrato(contrato) or {}
    sede_f = info.get("sede") or sede
    placa = ", ".join(info.get("placas") or []) or None
    filas = []
    for item in preparados:
        tipo = item["tipo"]
        if tipo == "CONTRATO":
            filas.append({"tipo": "CONTRATO_SIN_FIRMA", "data": item["original"], "mime": "application/pdf",
                          "firmado": False, "nombre": nombre_archivo(contrato, tipo, hoy, firmado=False)})
        filas.append({"tipo": tipo, "data": item["firmado"], "mime": "application/pdf", "firmado": True,
                      "nombre": nombre_archivo(contrato, tipo, hoy, item.get("idioma")),
                      "plantilla_id": item["plantilla_id"], "pagina": item["pagina"] + 1})
    for a in adjuntos or []:
        filas.append({"tipo": a["tipo"], "data": a["data"], "mime": a["mime"], "firmado": False,
                      "nombre": nombre_archivo(contrato, a["tipo"], hoy, ext=a["ext"])})

    def _upsert(conn, carpeta):
        conn.execute(text("""
            INSERT INTO operational.doc_contratos
                (contrato, placa, sede_nombre, creado_por, tramite, requeridos, firmante_nombre,
                 idioma, carpeta_id, firmado_at)
            VALUES (:c, :p, :s, :u, :t, :r, :f, :i, :cp, now())
            ON CONFLICT (contrato) DO UPDATE
                SET actualizado_por = :u, actualizado_at = now(), firmado_at = now(),
                    placa = COALESCE(EXCLUDED.placa, operational.doc_contratos.placa),
                    tramite = EXCLUDED.tramite, requeridos = EXCLUDED.requeridos,
                    firmante_nombre = EXCLUDED.firmante_nombre, idioma = EXCLUDED.idioma,
                    carpeta_id = EXCLUDED.carpeta_id,
                    sede_nombre = COALESCE(EXCLUDED.sede_nombre, operational.doc_contratos.sede_nombre)
        """), {"c": contrato, "p": placa, "s": sede_f, "u": usuario, "t": tramite,
               "r": list(TRAMITES[tramite]["requeridos"]), "f": (firmante or "").strip() or None,
               "i": idioma, "cp": carpeta})

    return _subir_y_registrar(contrato, filas, usuario, _upsert)


def agregar_adjuntos(contrato: int, adjuntos: list[dict], usuario: str) -> dict:
    """Agrega (o reemplaza) comprobante de pago / factura electronica de un contrato que
    ya tiene expediente, sin volver a firmar nada."""
    hoy = pd.Timestamp.now(tz="America/Bogota").date()
    filas = [{"tipo": a["tipo"], "data": a["data"], "mime": a["mime"], "firmado": False,
              "nombre": nombre_archivo(contrato, a["tipo"], hoy, ext=a["ext"])} for a in adjuntos]
    return _subir_y_registrar(int(contrato), filas, usuario)


def eliminar_expediente(contrato: int, usuario: str) -> None:
    """Borra el expediente (p.ej. una prueba): documentos a eliminado = TRUE (los
    objetos quedan en Storage), la fila de doc_contratos se borra y la carpeta del
    contrato se quita si queda vacia."""
    exp = expediente(contrato)
    execute_write("""
        UPDATE operational.documentos SET eliminado = TRUE, eliminado_por = :u, eliminado_at = now()
        WHERE contrato = :c AND tipo_documento IS NOT NULL AND NOT eliminado;
        DELETE FROM operational.doc_contratos WHERE contrato = :c;
    """, {"c": int(contrato), "u": usuario})
    if exp and pd.notna(exp.get("carpeta_id")):
        execute_write("""
            UPDATE operational.documentos SET carpeta_id = (
                SELECT parent_id FROM operational.doc_carpetas WHERE carpeta_id = :cp)
            WHERE carpeta_id = :cp AND eliminado;
            DELETE FROM operational.doc_carpetas c WHERE c.carpeta_id = :cp
              AND NOT EXISTS (SELECT 1 FROM operational.documentos d WHERE d.carpeta_id = c.carpeta_id)
              AND NOT EXISTS (SELECT 1 FROM operational.doc_carpetas h WHERE h.parent_id = c.carpeta_id);
        """, {"cp": int(exp["carpeta_id"])})


def migrar_a_contrato(usuario: str = "migracion") -> list[str]:
    """Una vez (2026-11-11): de Contratos/<PLACA>/<AAAA-MM-DD>_<CONTRATO> a
    Contratos/<CONTRATO>, sin la placa en los nombres; mueve tambien los objetos de
    Storage. Idempotente: lo que ya esta en contratos/<CONTRATO>/ no se toca."""
    log = []
    for e in D.load_query("SELECT contrato, placa, carpeta_id FROM operational.doc_contratos").itertuples():
        c, pl = int(e.contrato), e.placa
        nueva = carpeta_contrato(c, usuario)
        docs = D.load_query("""
            SELECT documento_id, nombre, storage_path FROM operational.documentos
            WHERE contrato = :c AND tipo_documento IS NOT NULL
        """, {"c": c})
        for d in docs.itertuples():
            n_nom = d.nombre.replace(f"{c}_{pl}_", f"{c}_")
            path = d.storage_path
            if not path.startswith(f"contratos/{c}/"):
                obj = path.rsplit("/", 1)[-1].replace(f"{c}_{pl}_", f"{c}_")
                nuevo = f"{_storage_dir(c)}/{obj}"
                S.move(path, nuevo)
                path = nuevo
                log.append(f"{d.storage_path} -> {nuevo}")
            execute_write("""
                UPDATE operational.documentos SET carpeta_id = :cp, nombre = :n, storage_path = :p
                WHERE documento_id = :id
            """, {"cp": nueva, "n": n_nom, "p": path, "id": int(d.documento_id)})
        execute_write("UPDATE operational.doc_contratos SET carpeta_id = :cp WHERE contrato = :c",
                      {"cp": nueva, "c": c})
    # carpetas viejas (placa / fecha_contrato) que quedaron vacias, dos pasadas: hijas y padres
    for _ in range(2):
        execute_write("""
            DELETE FROM operational.doc_carpetas c
            WHERE c.parent_id = (SELECT carpeta_id FROM operational.doc_carpetas
                                 WHERE parent_id IS NULL AND nombre = :r)
              AND c.nombre !~ '^[0-9]+$'
              AND NOT EXISTS (SELECT 1 FROM operational.documentos d WHERE d.carpeta_id = c.carpeta_id)
              AND NOT EXISTS (SELECT 1 FROM operational.doc_carpetas h WHERE h.parent_id = c.carpeta_id);
            DELETE FROM operational.doc_carpetas c
            WHERE c.parent_id IN (SELECT x.carpeta_id FROM operational.doc_carpetas x
                                  JOIN operational.doc_carpetas r ON r.carpeta_id = x.parent_id
                                  WHERE r.parent_id IS NULL AND r.nombre = :r AND x.nombre !~ '^[0-9]+$')
              AND NOT EXISTS (SELECT 1 FROM operational.documentos d WHERE d.carpeta_id = c.carpeta_id)
              AND NOT EXISTS (SELECT 1 FROM operational.doc_carpetas h WHERE h.parent_id = c.carpeta_id);
        """, {"r": CARPETA_RAIZ})
    return log


# =============================================================================
# Validacion (como Facturas)
# =============================================================================
ESTADOS = {
    "OK": "Al día",
    "PENDIENTE": "Pendiente: el contrato aún no llega del sistema",
    "INCOMPLETO": "Faltan documentos firmados",
    "FALTA_ADJ": "Falta comprobante o factura",
    "SIN_DOCS": "Sin documentos",
}


def validacion(desde: date, hasta: date, sedes: list[str] | None = None) -> pd.DataFrame:
    """Una fila por contrato: los expedientes firmados en el rango + los contratos del
    sistema entregados en el rango (desde FECHA_INICIO) sin expediente."""
    d0 = max(desde, FECHA_INICIO)
    exp = D.load_query("""
        SELECT e.contrato, e.sede_nombre, e.creado_por, e.creado_at,
               e.tramite, e.requeridos, e.firmante_nombre,
               COALESCE(array_agg(DISTINCT d.tipo_documento)
                        FILTER (WHERE d.tipo_documento IS NOT NULL), '{}') AS tipos
        FROM operational.doc_contratos e
        LEFT JOIN operational.documentos d
               ON d.contrato = e.contrato AND NOT d.eliminado
        WHERE (COALESCE(e.firmado_at, e.creado_at) AT TIME ZONE 'America/Bogota')::date BETWEEN :d AND :h
        GROUP BY e.contrato
    """, {"d": desde, "h": hasta})
    sis = D.load_query("""
        SELECT numero_contrato::bigint AS contrato
        FROM silver.vw_rentals_full
        WHERE fecha_handover_real::date BETWEEN :d AND :h
          AND TRIM(COALESCE(placa, '')) <> '' AND COALESCE(revenue_total_usd, 0) > 0
    """, {"d": d0, "h": hasta}) if d0 <= hasta else pd.DataFrame(columns=["contrato"])
    # int() nativo: to_py no entra a las listas y np.int64 rompe psycopg2 (numpy 2.x)
    todos = sorted({int(x) for x in exp["contrato"]} | {int(x) for x in sis["contrato"]})
    if not todos:
        return pd.DataFrame()
    hdr = D.load_query("""
        SELECT numero_contrato::bigint AS contrato, TRIM(placa) AS placa, sede_handover,
               fecha_handover_real::date AS entrega
        FROM silver.vw_rentals_full WHERE numero_contrato::bigint = ANY(:cs)
    """, {"cs": todos})
    seg = D.load_query("""
        SELECT rv.rntl_mvnr::bigint AS contrato, TRIM(dv.vhcl_plate) AS placa
        FROM silver.fact_rental_vehicles rv
        JOIN silver.dim_vehicles dv ON dv.vhcl_int_num = rv.vhcl_int_num
        WHERE rv.mndt_code = 409 AND rv.rntl_mvnr::bigint = ANY(:cs)
          AND NULLIF(TRIM(dv.vhcl_plate), '') IS NOT NULL
    """, {"cs": todos})
    placas: dict[int, set] = {}
    for c, p in list(zip(hdr["contrato"], hdr["placa"])) + list(zip(seg["contrato"], seg["placa"])):
        if p:
            placas.setdefault(int(c), set()).add(normalizar_placa(p))
    hdr = hdr.drop_duplicates("contrato").set_index("contrato")

    filas = []
    exp_by = {int(r.contrato): r for r in exp.itertuples()}
    for c in todos:
        e = exp_by.get(c)
        en_sis = c in hdr.index
        pls = sorted(placas.get(c, set()))
        fila = {"contrato": c, "placas_sistema": ", ".join(pls),
                "sede": hdr.at[c, "sede_handover"] if en_sis else (e.sede_nombre if e is not None else None),
                "entrega": hdr.at[c, "entrega"] if en_sis else None,
                "tramite": TRAMITES.get(e.tramite, {}).get("nombre", "") if e is not None else "",
                "firmante": (e.firmante_nombre or "") if e is not None else "",
                "creado_por": e.creado_por if e is not None else "",
                "creado_at": e.creado_at if e is not None else None, "faltan": ""}
        if e is None:
            fila["estado"] = "SIN_DOCS"
            fila["faltan"] = ", ".join([TIPOS[t] for t in TRAMITES["RENTA"]["requeridos"]] +
                                       [ADJUNTOS[t] for t in ADJUNTOS_REQUERIDOS])
        else:
            req = list(e.requeridos) if isinstance(e.requeridos, (list, tuple)) and len(e.requeridos) \
                else TRAMITES["RENTA"]["requeridos"]
            tiene = set(e.tipos or [])
            faltan = [TIPOS[t] for t in req if t not in tiene]
            faltan_adj = [ADJUNTOS[t] for t in ADJUNTOS_REQUERIDOS if t not in tiene]
            fila["faltan"] = ", ".join(faltan + faltan_adj)
            if faltan:
                fila["estado"] = "INCOMPLETO"
            elif faltan_adj:
                fila["estado"] = "FALTA_ADJ"
            elif not en_sis:
                fila["estado"] = "PENDIENTE"
            else:
                fila["estado"] = "OK"
        filas.append(fila)
    df = pd.DataFrame(filas)
    if sedes:
        df = df[df["sede"].isin(sedes) | df["sede"].isna()]
    return df
