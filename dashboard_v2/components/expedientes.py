"""
Expedientes de contrato firmados (sobre components/documentos.py + Supabase Storage).

Flujo (2026-11-10):
  1. El asesor digita PLACA + CONTRATO, elige el TRAMITE y sube SOLO el PDF del contrato.
     - RENTA: contrato + addendum + informacion de renta (ES o EN, segun el cliente).
     - SOLO_CONTRATO: solo el contrato (no todo lo que se firma lleva los anexos).
  2. Los anexos salen de PLANTILLAS fijas (operational.doc_plantillas: una activa por
     tipo x idioma, versionadas). Cada plantilla trae sus CAMPOS en posiciones exactas
     (firma, nombre del cliente, numero de contrato, fecha), p.ej. el addendum lleva
     "agreement number", "Print Name", "Signature" y "Date".
  3. El cliente firma UNA vez; la firma (y su nombre) quedan en todos los documentos.
     Vista previa de todos -> guardar.
  4. Carpetas  Contratos / <PLACA> / <AAAA-MM-DD>_<CONTRATO>  (orden alfabetico =
     cronologico) y nombres  <CONTRATO>_<PLACA>_<TIPO>_<AAAAMMDD>.pdf
  5. Validacion (como Facturas) contra silver: pendiente / placa no coincide /
     faltan documentos (segun el tramite) / al dia; y contratos del sistema sin
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

API_VERSION = 4

TIPOS = {
    "CONTRATO": "Contrato",
    "ADENDUM": "Addendum",
    "INFO_GENERAL": "Información de renta",
}
# Como se llama cada tipo en el NOMBRE del archivo
TIPO_ARCHIVO = {"CONTRATO": "CONTRATO", "ADENDUM": "ADDENDUM", "INFO_GENERAL": "INFO_RENTA"}
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
    t = TIPOS.get(tipo, "Contrato sin firma (original)" if tipo == "CONTRATO_SIN_FIRMA" else tipo)
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


def nombre_archivo(contrato: int, placa: str, tipo: str, fecha: date, idioma: str | None = None,
                   firmado: bool = True) -> str:
    """9524178852_QQT746_ADDENDUM_20261110.pdf · ..._INFO_RENTA_ES_... · ..._CONTRATO_SIN_FIRMA_..."""
    t = TIPO_ARCHIVO.get(tipo, tipo) + (f"_{idioma}" if idioma else "") + ("" if firmado else "_SIN_FIRMA")
    return f"{int(contrato)}_{placa}_{t}_{fecha:%Y%m%d}.pdf"


def nombre_carpeta(contrato: int, fecha: date) -> str:
    return f"{fecha:%Y-%m-%d}_{int(contrato)}"


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
            placa           text NOT NULL,
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
    execute_write(f"""
        CREATE OR REPLACE VIEW operational.vw_documentos_contratos AS
        SELECT e.placa,
               e.contrato,
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
# Carpetas automaticas  Contratos / PLACA / AAAA-MM-DD_CONTRATO
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


def carpeta_contrato(placa: str, contrato: int, fecha: date, usuario: str) -> int:
    raiz = _carpeta(CARPETA_RAIZ, None, usuario)
    cp = _carpeta(placa, raiz, usuario)
    return _carpeta(nombre_carpeta(contrato, fecha), cp, usuario)


# =============================================================================
# Expedientes
# =============================================================================
def expediente(contrato: int) -> dict | None:
    df = D.load_query("SELECT * FROM operational.doc_contratos WHERE contrato = :c", {"c": int(contrato)})
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
        ORDER BY CASE d.tipo_documento WHEN 'CONTRATO' THEN 1 WHEN 'ADENDUM' THEN 2
                                       WHEN 'INFO_GENERAL' THEN 3 ELSE 4 END, d.subido_at DESC
    """, {"c": int(contrato)})


def contratos_de_placa(placa: str) -> pd.DataFrame:
    """Expedientes de la placa (digitada o, segun el sistema, en algun tramo del
    contrato), del mas reciente al mas viejo."""
    return D.load_query("""
        SELECT e.contrato, e.placa, e.tramite, e.requeridos, e.firmante_nombre, e.idioma,
               e.creado_por, e.creado_at, COALESCE(e.firmado_at, e.creado_at) AS firmado_at,
               COUNT(d.documento_id) FILTER (WHERE d.firmado_por IS NOT NULL
                   AND d.tipo_documento IN ('CONTRATO','ADENDUM','INFO_GENERAL')) AS firmados,
               MAX(d.subido_at) AS ultima_carga
        FROM operational.doc_contratos e
        LEFT JOIN operational.documentos d
               ON d.contrato = e.contrato AND NOT d.eliminado AND d.tipo_documento IS NOT NULL
        WHERE e.placa = :p
           OR EXISTS (SELECT 1 FROM operational.documentos x
                      WHERE x.contrato = e.contrato AND NOT x.eliminado AND :p = ANY(x.placas))
        GROUP BY e.contrato
        ORDER BY COALESCE(e.firmado_at, e.creado_at) DESC
    """, {"p": placa})


def placas_flota() -> pd.DataFrame:
    """Flota activa (ultimo dia de gold_carro_dia): placa, sede, acriss. Para el selector."""
    return D.load_query("""
        SELECT placa, sede, acriss FROM silver.gold_carro_dia
        WHERE fecha = (SELECT MAX(fecha) FROM silver.gold_carro_dia)
        ORDER BY placa
    """)


def placas_con_documentos() -> pd.DataFrame:
    """Placas que ya tienen expedientes, con cuantos contratos y el ultimo firmado."""
    return D.load_query("""
        SELECT placa, COUNT(*) AS contratos, MAX(COALESCE(firmado_at, creado_at)) AS ultimo
        FROM operational.doc_contratos GROUP BY placa ORDER BY placa
    """)


def contratos_sistema_placa(placa: str, limite: int = 15) -> pd.DataFrame:
    """Contratos recientes de la placa segun el sistema (header + tramos), del mas nuevo
    al mas viejo, para elegir en vez de digitar."""
    return D.load_query("""
        WITH c AS (
            SELECT numero_contrato::bigint AS contrato FROM silver.vw_rentals_full
            WHERE TRIM(placa) = :p
            UNION
            SELECT rv.rntl_mvnr::bigint FROM silver.fact_rental_vehicles rv
            JOIN silver.dim_vehicles dv ON dv.vhcl_int_num = rv.vhcl_int_num
            WHERE rv.mndt_code = 409 AND TRIM(dv.vhcl_plate) = :p
        )
        SELECT r.numero_contrato::bigint AS contrato, r.fecha_handover_real::date AS entrega,
               r.fecha_devolucion_real::date AS devolucion, r.sede_handover
        FROM silver.vw_rentals_full r JOIN c ON c.contrato = r.numero_contrato::bigint
        WHERE COALESCE(r.revenue_total_usd, 0) > 0
        ORDER BY r.fecha_handover_real DESC NULLS LAST
        LIMIT :n
    """, {"p": placa, "n": int(limite)})


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


def _storage_dir(placa: str, carpeta_nombre: str) -> str:
    """Misma estructura que el dashboard: contratos/<PLACA>/<AAAA-MM-DD>_<CONTRATO>"""
    return f"contratos/{placa}/{carpeta_nombre}"


def _objeto(nombre: str) -> str:
    """Nombre del objeto en Storage: el nombre limpio + hora + 4 hex (unico aunque se
    re-firme el mismo dia o dos personas guarden en el mismo segundo)."""
    base = nombre[:-4] if nombre.lower().endswith(".pdf") else nombre
    return f"{base}_{pd.Timestamp.now(tz='America/Bogota'):%H%M%S}_{uuid.uuid4().hex[:4]}.pdf"


def guardar(contrato: int, placa: str, preparados: list[dict], usuario: str, tramite: str,
            firmante: str = "", idioma: str | None = None, sede: str | None = None) -> dict:
    """Guarda el expediente de forma ATOMICA (pensado para ~7 personas a la vez):
      1. sube todos los PDF a Storage (rutas unicas, no chocan entre usuarios);
      2. registra TODO en UNA transaccion con un candado por contrato
         (pg_advisory_xact_lock): si dos personas guardan el mismo contrato a la vez,
         la segunda espera a la primera y luego reemplaza limpio; nunca queda medio
         expediente ni dos versiones vigentes del mismo tipo;
      3. si la transaccion falla, borra lo que subio en el paso 1.
    Contrato SIN firmar (traza) + los firmados, en Contratos/PLACA/AAAA-MM-DD_CONTRATO.
    Devuelve {tipo: documento_id}."""
    contrato = int(contrato)
    hoy = pd.Timestamp.now(tz="America/Bogota").date()
    exp = expediente(contrato)
    if exp and exp["placa"] != placa:
        raise ValueError(f"El contrato {contrato} ya tiene expediente con la placa {exp['placa']}. "
                         "Corrige la placa desde Validación antes de volver a firmar.")
    carpeta = int(exp["carpeta_id"]) if exp and pd.notna(exp.get("carpeta_id")) else \
        carpeta_contrato(placa, contrato, hoy, usuario)
    carpeta_nombre = D.load_query("SELECT nombre FROM operational.doc_carpetas WHERE carpeta_id = :c",
                                  {"c": carpeta}).iloc[0, 0]
    info = D.info_contrato(contrato) or {"contrato": contrato, "placas": [], "sede": sede}
    sede_f = info.get("sede") or sede

    # 1. subir todo a Storage
    filas = []
    for item in preparados:
        tipo = item["tipo"]
        if tipo == "CONTRATO":
            filas.append({"tipo": "CONTRATO_SIN_FIRMA", "data": item["original"], "firmado": False,
                          "nombre": nombre_archivo(contrato, placa, tipo, hoy, firmado=False),
                          "plantilla_id": None, "pagina": None})
        filas.append({"tipo": tipo, "data": item["firmado"], "firmado": True,
                      "nombre": nombre_archivo(contrato, placa, tipo, hoy, item.get("idioma")),
                      "plantilla_id": item["plantilla_id"], "pagina": item["pagina"] + 1})
    subidos = []
    try:
        for f in filas:
            f["path"] = f"{_storage_dir(placa, carpeta_nombre)}/{_objeto(f['nombre'])}"
            S.upload(f["path"], f["data"], "application/pdf")
            subidos.append(f["path"])

        # 2. una sola transaccion, con candado por contrato
        ids = {}
        with get_engine().begin() as conn:
            conn.execute(text("SET LOCAL search_path TO operational, public"))
            conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": contrato})
            actual = conn.execute(text("SELECT placa FROM operational.doc_contratos WHERE contrato = :c"),
                                  {"c": contrato}).scalar()
            if actual is not None and actual != placa:
                raise ValueError(f"Otro usuario acaba de guardar el contrato {contrato} con la placa {actual}.")
            conn.execute(text("""
                INSERT INTO operational.doc_contratos
                    (contrato, placa, sede_nombre, creado_por, tramite, requeridos, firmante_nombre,
                     idioma, carpeta_id, firmado_at)
                VALUES (:c, :p, :s, :u, :t, :r, :f, :i, :cp, now())
                ON CONFLICT (contrato) DO UPDATE
                    SET actualizado_por = :u, actualizado_at = now(), firmado_at = now(),
                        tramite = EXCLUDED.tramite, requeridos = EXCLUDED.requeridos,
                        firmante_nombre = EXCLUDED.firmante_nombre, idioma = EXCLUDED.idioma,
                        carpeta_id = COALESCE(operational.doc_contratos.carpeta_id, EXCLUDED.carpeta_id),
                        sede_nombre = COALESCE(EXCLUDED.sede_nombre, operational.doc_contratos.sede_nombre)
            """), {"c": contrato, "p": placa, "s": sede_f, "u": usuario, "t": tramite,
                   "r": list(TRAMITES[tramite]["requeridos"]), "f": (firmante or "").strip() or None,
                   "i": idioma, "cp": carpeta})
            tipos = sorted({f["tipo"] for f in filas})
            conn.execute(text("""
                UPDATE operational.documentos
                SET eliminado = TRUE, eliminado_por = :u, eliminado_at = now()
                WHERE contrato = :c AND tipo_documento = ANY(:t) AND NOT eliminado
            """), {"c": contrato, "t": tipos, "u": usuario})
            sin_firma_id = None
            for f in filas:
                nid = conn.execute(text("""
                    INSERT INTO operational.documentos
                        (carpeta_id, nombre, storage_path, mime_type, tamano_bytes, sha256, subido_por,
                         firmado_de, firmado_por, firmado_at, contrato, placas, sede_nombre,
                         firma_pagina, tipo_documento, plantilla_id)
                    VALUES (:cp, :n, :p, 'application/pdf', :t, :h, :u,
                            :fd, :fp, CASE WHEN :fp IS NULL THEN NULL ELSE now() END,
                            :c, :pl, :s, :pg, :td, :pi)
                    RETURNING documento_id
                """), {"cp": carpeta, "n": f["nombre"], "p": f["path"], "t": len(f["data"]),
                       "h": hashlib.sha256(f["data"]).hexdigest(), "u": usuario,
                       "fd": sin_firma_id if f["tipo"] == "CONTRATO" else None,
                       "fp": usuario if f["firmado"] else None, "c": contrato,
                       "pl": list(info.get("placas") or []), "s": sede_f, "pg": f["pagina"],
                       "td": f["tipo"], "pi": f["plantilla_id"]}).scalar()
                if f["tipo"] == "CONTRATO_SIN_FIRMA":
                    sin_firma_id = nid
                else:
                    ids[f["tipo"]] = nid
        return ids
    except Exception:
        # 3. nada a medias: lo subido en esta corrida se borra
        if subidos:
            try:
                S.delete(subidos)
            except Exception:  # noqa: BLE001
                pass
        raise


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


def corregir_placa(contrato: int, placa_nueva: str, usuario: str) -> None:
    """Cambia la placa del expediente: mueve su carpeta bajo Contratos/<nueva>, renombra
    los archivos y MUEVE los objetos de Storage a contratos/<nueva>/... (misma
    estructura que el dashboard)."""
    exp = expediente(contrato)
    if not exp:
        raise ValueError("Ese contrato no tiene expediente.")
    vieja = exp["placa"]
    raiz = _carpeta(CARPETA_RAIZ, None, usuario)
    nueva_padre = _carpeta(placa_nueva, raiz, usuario)
    docs = D.load_query("""
        SELECT documento_id, storage_path FROM operational.documentos
        WHERE contrato = :c AND tipo_documento IS NOT NULL
    """, {"c": int(contrato)})
    pref_v, pref_n = f"contratos/{vieja}/", f"contratos/{placa_nueva}/"
    movidos = []
    for r in docs.itertuples():
        if r.storage_path.startswith(pref_v):
            nuevo = pref_n + r.storage_path[len(pref_v):]
            nuevo = nuevo.replace(f"_{vieja}_", f"_{placa_nueva}_")
            S.move(r.storage_path, nuevo)
            movidos.append({"id": int(r.documento_id), "p": nuevo})
    for m in movidos:
        execute_write("UPDATE operational.documentos SET storage_path = :p WHERE documento_id = :id", m)
    execute_write("""
        UPDATE operational.doc_carpetas SET parent_id = :np WHERE carpeta_id = :cp;
        UPDATE operational.documentos SET nombre = replace(nombre, :sv, :sn)
        WHERE contrato = :c AND tipo_documento IS NOT NULL;
        UPDATE operational.doc_contratos
        SET placa = :pn, actualizado_por = :u, actualizado_at = now()
        WHERE contrato = :c
    """, {"c": int(contrato), "cp": int(exp["carpeta_id"]), "np": nueva_padre, "sv": f"_{vieja}_",
          "sn": f"_{placa_nueva}_", "pn": placa_nueva, "u": usuario})


# =============================================================================
# Validacion (como Facturas)
# =============================================================================
ESTADOS = {
    "OK": "Al día",
    "PENDIENTE": "Pendiente: el contrato aún no llega del sistema",
    "PLACA": "La placa no coincide con el sistema",
    "INCOMPLETO": "Faltan documentos firmados",
    "SIN_DOCS": "Sin documentos",
}


def validacion(desde: date, hasta: date, sedes: list[str] | None = None) -> pd.DataFrame:
    """Una fila por contrato: los expedientes firmados en el rango + los contratos del
    sistema entregados en el rango (desde FECHA_INICIO) sin expediente."""
    d0 = max(desde, FECHA_INICIO)
    exp = D.load_query("""
        SELECT e.contrato, e.placa AS placa_digitada, e.sede_nombre, e.creado_por, e.creado_at,
               e.tramite, e.requeridos, e.firmante_nombre,
               COALESCE(array_agg(DISTINCT d.tipo_documento)
                        FILTER (WHERE d.tipo_documento IS NOT NULL), '{}') AS tipos
        FROM operational.doc_contratos e
        LEFT JOIN operational.documentos d
               ON d.contrato = e.contrato AND NOT d.eliminado AND d.firmado_por IS NOT NULL
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
        fila = {"contrato": c, "placa_digitada": e.placa_digitada if e is not None else "",
                "placas_sistema": ", ".join(pls),
                "sede": hdr.at[c, "sede_handover"] if en_sis else (e.sede_nombre if e is not None else None),
                "entrega": hdr.at[c, "entrega"] if en_sis else None,
                "tramite": TRAMITES.get(e.tramite, {}).get("nombre", "") if e is not None else "",
                "firmante": (e.firmante_nombre or "") if e is not None else "",
                "creado_por": e.creado_por if e is not None else "",
                "creado_at": e.creado_at if e is not None else None, "faltan": ""}
        if e is None:
            fila["estado"] = "SIN_DOCS"
            fila["faltan"] = ", ".join(TIPOS[t] for t in TRAMITES["RENTA"]["requeridos"])
        else:
            req = list(e.requeridos) if isinstance(e.requeridos, (list, tuple)) and len(e.requeridos) \
                else TRAMITES["RENTA"]["requeridos"]
            faltan = [TIPOS[t] for t in req if t not in set(e.tipos or [])]
            fila["faltan"] = ", ".join(faltan)
            if faltan:
                fila["estado"] = "INCOMPLETO"
            elif not en_sis:
                fila["estado"] = "PENDIENTE"
            elif e.placa_digitada not in pls:
                fila["estado"] = "PLACA"
            else:
                fila["estado"] = "OK"
        filas.append(fila)
    df = pd.DataFrame(filas)
    if sedes:
        df = df[df["sede"].isin(sedes) | df["sede"].isna()]
    return df
