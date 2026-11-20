"""
Hojas de calculo dentro del dashboard (reemplazo de las hojas de Odoo Documents).

Motor: o-spreadsheet (el mismo de Odoo, LGPL), en el componente components/hoja_calculo/.
Las usuarias crean hojas, agregan columnas, pestanas y formulas sin pedirle nada al
desarrollador; se abren los .xlsx de Odoo/Excel y se descargan como .xlsx.

Donde vive cada cosa:
  - operational.documentos: la hoja es un documento mas de la carpeta (mime HOJA_MIME,
    storage_path virtual 'hoja:<uuid>', SIN objeto en Storage).
  - operational.hojas: el contenido VIVO (JSON nativo de o-spreadsheet) en la base, que
    SI tiene backups/PITR (Storage no). Se guarda solo mientras se escribe.
  - operational.hojas_versiones: una foto del contenido cada vez que alguien EMPIEZA a
    editar (= version anterior a su sesion) -> se puede volver atras.

Varias sedes a la vez: UNA persona edita y las demas ven en solo lectura con aviso de
quien la tiene. El turno de edicion vence a los BLOQUEO_MIN sin cambios (cada guardado lo
renueva), asi que una pestana olvidada no deja la hoja tomada para siempre.
"""
from __future__ import annotations

import io
import json
import uuid
import zipfile
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from sqlalchemy import text

from components import documentos as D
from components import storage as S
from components.common import execute_write, execute_write_returning, get_engine

API_VERSION = 1
HOJA_MIME = "application/vnd.trust.hoja+json"
XLSX_MIMES = {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
BLOQUEO_MIN = 10

_componente = components.declare_component(
    "hoja_calculo", path=str(Path(__file__).parent / "hoja_calculo"))


def es_hoja(fila) -> bool:
    return (fila.get("mime_type") or "") == HOJA_MIME


def es_xlsx(fila) -> bool:
    return (fila.get("mime_type") or "") in XLSX_MIMES or str(fila.get("nombre", "")).lower().endswith(".xlsx")


# =============================================================================
# Tablas
# =============================================================================
@st.cache_resource
def ensure_tables() -> bool:
    execute_write("""
        CREATE TABLE IF NOT EXISTS operational.hojas (
            documento_id    bigint PRIMARY KEY REFERENCES operational.documentos(documento_id),
            data            jsonb,                 -- NULL = falta convertir el xlsx de origen
            origen_xlsx_id  bigint REFERENCES operational.documentos(documento_id),
            revision        integer NOT NULL DEFAULT 0,
            editor          text,
            editor_hasta    timestamptz,
            actualizado_por text,
            actualizado_at  timestamptz
        );
        CREATE TABLE IF NOT EXISTS operational.hojas_versiones (
            version_id      bigserial PRIMARY KEY,
            documento_id    bigint NOT NULL REFERENCES operational.documentos(documento_id),
            data            jsonb NOT NULL,
            revision        integer,
            motivo          text,
            creado_por      text,
            creado_at       timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS hojas_versiones_doc_idx
            ON operational.hojas_versiones (documento_id, creado_at DESC);
    """, {})
    return True


# =============================================================================
# Crear / abrir
# =============================================================================
def _nombre_limpio(nombre: str) -> str:
    n = (nombre or "").strip()
    return n[:-5] if n.lower().endswith(".xlsx") else n


def crear(carpeta_id: int, nombre: str, usuario: str, origen_xlsx_id: int | None = None) -> int:
    """Hoja nueva (vacia) o a partir de un xlsx (se convierte en el navegador la primera
    vez que se abre). Devuelve el documento_id."""
    nombre = _nombre_limpio(nombre)
    if not nombre:
        raise ValueError("Ponle un nombre a la hoja.")
    with get_engine().begin() as conn:
        conn.execute(text("SET LOCAL search_path TO operational, public"))
        doc = conn.execute(text("""
            INSERT INTO operational.documentos
                (carpeta_id, nombre, storage_path, mime_type, tamano_bytes, subido_por)
            VALUES (:c, :n, :p, :m, 0, :u) RETURNING documento_id
        """), {"c": int(carpeta_id), "n": nombre, "p": f"hoja:{uuid.uuid4().hex}",
               "m": HOJA_MIME, "u": usuario}).scalar()
        conn.execute(text("""
            INSERT INTO operational.hojas (documento_id, data, origen_xlsx_id, actualizado_por, actualizado_at)
            VALUES (:d, CASE WHEN :o IS NULL THEN '{}'::jsonb ELSE NULL END, :o, :u, now())
        """), {"d": doc, "o": origen_xlsx_id, "u": usuario})
    return int(doc)


def convertir_xlsx(documento_xlsx: dict, usuario: str) -> int:
    """'Abrir y editar en la app' sobre un .xlsx: crea la hoja en la misma carpeta.
    El xlsx original queda en el historial (eliminado = TRUE) cuando la hoja se guarda
    por primera vez, para no tener dos archivos con el mismo nombre."""
    return crear(int(documento_xlsx["carpeta_id"]), documento_xlsx["nombre"], usuario,
                 origen_xlsx_id=int(documento_xlsx["documento_id"]))


def xlsx_a_archivos(data: bytes) -> dict:
    """Descomprime el xlsx en {ruta: texto XML}, que es lo que el motor sabe importar.
    Las imagenes no se traen (el motor las pediria a un servidor de archivos)."""
    out = {}
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for n in z.namelist():
            if n.endswith("/") or "/media/" in n:
                continue
            try:
                out[n] = z.read(n).decode("utf-8")
            except UnicodeDecodeError:
                continue
    return out


def abrir(documento_id: int) -> dict | None:
    df = D.load_query("""
        SELECT h.documento_id, h.data, h.origen_xlsx_id, h.revision, h.editor, h.editor_hasta,
               h.actualizado_por, h.actualizado_at, d.nombre, d.carpeta_id,
               (h.editor IS NOT NULL AND h.editor_hasta > now()) AS tomada
        FROM operational.hojas h JOIN operational.documentos d USING (documento_id)
        WHERE h.documento_id = :d
    """, {"d": int(documento_id)})
    if df.empty:
        return None
    r = df.iloc[0].to_dict()
    if isinstance(r["data"], str):
        r["data"] = json.loads(r["data"])
    return r


def estado(documento_id: int) -> dict:
    """Liviano (sin el contenido): quien tiene el turno y cuando se guardo."""
    df = D.load_query("""
        SELECT editor, editor_hasta, actualizado_por, actualizado_at, revision,
               (editor IS NOT NULL AND editor_hasta > now()) AS tomada
        FROM operational.hojas WHERE documento_id = :d
    """, {"d": int(documento_id)})
    return df.iloc[0].to_dict() if not df.empty else {}


def datos_iniciales(hoja: dict) -> dict:
    """Lo que recibe el componente: {'data': json} o {'xlsx': {archivos}} si falta convertir."""
    if hoja["data"] is not None:
        return {"data": hoja["data"]}
    org = D.load_query("SELECT storage_path FROM operational.documentos WHERE documento_id = :d",
                       {"d": int(hoja["origen_xlsx_id"])})
    return {"xlsx": xlsx_a_archivos(S.download(org.iloc[0, 0]))}


# =============================================================================
# Turno de edicion (uno a la vez) + guardado
# =============================================================================
def tomar(documento_id: int, usuario: str) -> tuple[bool, str | None]:
    """Toma el turno si esta libre, vencido o ya es suyo. Al EMPEZAR una sesion guarda una
    foto del contenido actual en hojas_versiones. Devuelve (ok, quien_la_tiene)."""
    with get_engine().begin() as conn:
        conn.execute(text("SET LOCAL search_path TO operational, public"))
        fila = conn.execute(text("""
            SELECT editor, editor_hasta > now() AS vigente, data IS NOT NULL AS tiene, revision
            FROM operational.hojas WHERE documento_id = :d FOR UPDATE
        """), {"d": int(documento_id)}).first()
        if fila is None:
            return False, None
        editor, vigente, tiene, rev = fila
        if editor and vigente and editor != usuario:
            return False, editor
        nueva_sesion = not (editor == usuario and vigente)
        if nueva_sesion and tiene:
            conn.execute(text("""
                INSERT INTO operational.hojas_versiones (documento_id, data, revision, motivo, creado_por)
                SELECT documento_id, data, revision, 'antes de editar (' || :u || ')', :u
                FROM operational.hojas WHERE documento_id = :d
            """), {"d": int(documento_id), "u": usuario})
        conn.execute(text(f"""
            UPDATE operational.hojas
            SET editor = :u, editor_hasta = now() + interval '{BLOQUEO_MIN} minutes'
            WHERE documento_id = :d
        """), {"d": int(documento_id), "u": usuario})
    return True, usuario


def soltar(documento_id: int, usuario: str) -> None:
    execute_write("""
        UPDATE operational.hojas SET editor = NULL, editor_hasta = NULL
        WHERE documento_id = :d AND editor = :u
    """, {"d": int(documento_id), "u": usuario})


def guardar(documento_id: int, usuario: str, data: dict) -> bool:
    """Guarda el contenido si el turno es de este usuario (y lo renueva). False = otra
    persona tomo la hoja (el turno de este usuario vencio)."""
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    with get_engine().begin() as conn:
        conn.execute(text("SET LOCAL search_path TO operational, public"))
        r = conn.execute(text(f"""
            UPDATE operational.hojas
            SET data = CAST(:j AS jsonb), revision = revision + 1,
                actualizado_por = :u, actualizado_at = now(),
                editor_hasta = now() + interval '{BLOQUEO_MIN} minutes'
            WHERE documento_id = :d AND editor = :u
            RETURNING origen_xlsx_id, revision
        """), {"d": int(documento_id), "u": usuario, "j": payload}).first()
        if r is None:
            return False
        conn.execute(text("""
            UPDATE operational.documentos SET tamano_bytes = :t WHERE documento_id = :d
        """), {"d": int(documento_id), "t": len(payload.encode())})
        if r[0] is not None and r[1] == 1:   # primera vez: el xlsx original pasa al historial
            conn.execute(text("""
                UPDATE operational.documentos
                SET eliminado = TRUE, eliminado_por = :u, eliminado_at = now(),
                    descripcion = 'Convertido a hoja de cálculo (documento ' || :d || ')'
                WHERE documento_id = :o AND NOT eliminado
            """), {"o": int(r[0]), "u": usuario, "d": int(documento_id)})
    return True


def versiones(documento_id: int) -> pd.DataFrame:
    return D.load_query("""
        SELECT version_id, revision, motivo, creado_por, creado_at,
               pg_column_size(data) AS bytes
        FROM operational.hojas_versiones WHERE documento_id = :d
        ORDER BY creado_at DESC LIMIT 50
    """, {"d": int(documento_id)})


def restaurar(documento_id: int, version_id: int, usuario: str) -> bool:
    """Vuelve a una version anterior (la actual queda guardada como version). Requiere el turno."""
    ok, _ = tomar(documento_id, usuario)
    if not ok:
        return False
    with get_engine().begin() as conn:
        conn.execute(text("SET LOCAL search_path TO operational, public"))
        conn.execute(text("""
            INSERT INTO operational.hojas_versiones (documento_id, data, revision, motivo, creado_por)
            SELECT documento_id, data, revision, 'antes de restaurar', :u
            FROM operational.hojas WHERE documento_id = :d AND data IS NOT NULL
        """), {"d": int(documento_id), "u": usuario})
        conn.execute(text("""
            UPDATE operational.hojas h SET data = v.data, revision = h.revision + 1,
                   actualizado_por = :u, actualizado_at = now()
            FROM operational.hojas_versiones v
            WHERE h.documento_id = :d AND v.version_id = :v AND v.documento_id = :d
        """), {"d": int(documento_id), "v": int(version_id), "u": usuario})
    return True


# =============================================================================
# Componente
# =============================================================================
def editor(key: str, nombre: str, iniciales: dict, solo_lectura: bool, alto: int = 720):
    """Monta la hoja. Devuelve el ultimo evento {tipo, seq, data} o None.
    OJO: los args NO deben cambiar mientras la hoja esta abierta (el componente solo
    monta con el primer render); para recargar, cambiar la key."""
    return _componente(key=key, nombre=nombre, solo_lectura=solo_lectura, alto=alto,
                       default=None, **iniciales)
