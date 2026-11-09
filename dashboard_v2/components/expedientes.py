"""
Expedientes de contrato firmados (sobre components/documentos.py + Supabase Storage).

Flujo (2026-11-09):
  1. El asesor digita PLACA + CONTRATO y sube SOLO el PDF del contrato.
  2. El adendum y la informacion general salen de PLANTILLAS fijas (las mismas para
     todos los contratos; operational.doc_plantillas, una activa por tipo, versionadas).
  3. El cliente firma UNA vez con el mouse/dedo; la firma se estampa en los 3
     documentos (cada plantilla tiene su pagina/posicion de firma configurada; la
     del contrato la elige el asesor). Vista previa de los 3 -> guardar.
  4. Carpetas automaticas  Contratos / <PLACA> / <CONTRATO>  en doc_carpetas, y
     nombres con formato fijo:  <CONTRATO>_<PLACA>_<TIPO>.pdf
  5. Validacion (como Facturas): el contrato aun no esta en el sistema -> pendiente
     (el pipeline lo trae de madrugada); despues se cruza con silver: la placa
     digitada debe ser una de las placas del contrato, y deben estar los 3 firmados.
     Al reves: contratos del sistema sin expediente = "sin documentos".

operational.doc_contratos = 1 fila por contrato (placa digitada, quien lo creo).
Los documentos son filas de operational.documentos con contrato + tipo_documento.
Re-firmar un tipo reemplaza al anterior (el viejo queda con eliminado = TRUE).
"""
from __future__ import annotations

import re
from datetime import date

import pandas as pd
import streamlit as st

from components import documentos as D
from components import storage as S
from components.common import execute_write, execute_write_returning

API_VERSION = 1

TIPOS = {
    "CONTRATO": "Contrato",
    "ADENDUM": "Adendum",
    "INFO_GENERAL": "Información general",
}
TIPOS_PLANTILLA = ("ADENDUM", "INFO_GENERAL")
TIPOS_REQUERIDOS = ("CONTRATO", "ADENDUM", "INFO_GENERAL")
CARPETA_RAIZ = "Contratos"

# Desde cuando se exige expediente. Los contratos anteriores no salen como
# "sin documentos" en la validacion. AJUSTAR al dia que arranque el uso real.
FECHA_INICIO = date(2026, 11, 9)

_RE_PLACA = re.compile(r"^[A-Z]{3}[0-9]{3}$")      # carros en Colombia: ABC123
_RE_CONTRATO = re.compile(r"^[0-9]{10}$")          # contratos Sixt: 10 digitos


# =============================================================================
# Formatos
# =============================================================================
def normalizar_placa(txt: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (txt or "").upper())


def placa_valida(p: str) -> bool:
    return bool(_RE_PLACA.match(p or ""))


def contrato_valido(c: str) -> bool:
    return bool(_RE_CONTRATO.match((c or "").strip()))


def nombre_archivo(contrato: int, placa: str, tipo: str, firmado: bool = True) -> str:
    """Formato fijo: 9524178852_QQT746_CONTRATO.pdf (sin firmar: ..._CONTRATO_SIN_FIRMA.pdf)."""
    return f"{int(contrato)}_{placa}_{tipo}{'' if firmado else '_SIN_FIRMA'}.pdf"


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
            version        integer NOT NULL,
            nombre         text NOT NULL,
            storage_path   text NOT NULL UNIQUE,
            firma_pagina   integer,            -- 1-based; NULL = ultima pagina
            firma_x        numeric NOT NULL DEFAULT 64,   -- % desde la izquierda
            firma_y        numeric NOT NULL DEFAULT 8,    -- % desde abajo
            firma_ancho    numeric NOT NULL DEFAULT 28,   -- % del ancho de la hoja
            activa         boolean NOT NULL DEFAULT TRUE,
            subido_por     text,
            subido_at      timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tipo, version)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS doc_plantillas_activa_uq
            ON operational.doc_plantillas (tipo) WHERE activa;
        CREATE TABLE IF NOT EXISTS operational.doc_contratos (
            contrato       bigint PRIMARY KEY,
            placa          text NOT NULL,
            sede_nombre    text,
            creado_por     text,
            creado_at      timestamptz NOT NULL DEFAULT now(),
            actualizado_por text,
            actualizado_at timestamptz
        );
        CREATE INDEX IF NOT EXISTS doc_contratos_placa_idx ON operational.doc_contratos (placa);
        -- un solo documento VIGENTE por (contrato, tipo); re-firmar marca el viejo eliminado
        CREATE UNIQUE INDEX IF NOT EXISTS documentos_contrato_tipo_uq
            ON operational.documentos (contrato, tipo_documento)
            WHERE NOT eliminado AND tipo_documento IS NOT NULL AND contrato IS NOT NULL;
    """, {})
    return True


# =============================================================================
# Plantillas
# =============================================================================
def plantillas_activas() -> pd.DataFrame:
    return D.load_query("""
        SELECT plantilla_id, tipo, version, nombre, storage_path, firma_pagina,
               firma_x::float AS firma_x, firma_y::float AS firma_y,
               firma_ancho::float AS firma_ancho, subido_por, subido_at
        FROM operational.doc_plantillas WHERE activa ORDER BY tipo
    """)


def historial_plantillas() -> pd.DataFrame:
    return D.load_query("""
        SELECT plantilla_id, tipo, version, nombre, activa, subido_por, subido_at
        FROM operational.doc_plantillas ORDER BY tipo, version DESC
    """)


def subir_plantilla(tipo: str, nombre: str, data: bytes, usuario: str, pagina: int | None,
                    x: float, y: float, ancho: float) -> int:
    """Nueva VERSION de la plantilla (la anterior queda inactiva, no se borra: los
    expedientes viejos siguen apuntando a la version con la que se firmaron)."""
    assert tipo in TIPOS_PLANTILLA
    D.info_pdf(data)   # valida que sea un PDF legible
    path = f"plantillas/{tipo}/{pd.Timestamp.now(tz='America/Bogota'):%Y%m%d_%H%M%S}_{D._slug(nombre)}"
    S.upload(path, data, "application/pdf")
    try:
        return execute_write_returning("""
            WITH off AS (
                UPDATE operational.doc_plantillas SET activa = FALSE
                WHERE tipo = :t AND activa RETURNING 1
            )
            INSERT INTO operational.doc_plantillas
                (tipo, version, nombre, storage_path, firma_pagina, firma_x, firma_y,
                 firma_ancho, activa, subido_por)
            SELECT :t, COALESCE((SELECT MAX(version) FROM operational.doc_plantillas WHERE tipo = :t), 0) + 1,
                   :n, :p, :pg, :x, :y, :a, TRUE, :u
            FROM (SELECT COUNT(*) FROM off) z
            RETURNING plantilla_id
        """, {"t": tipo, "n": nombre, "p": path, "pg": pagina, "x": x, "y": y, "a": ancho, "u": usuario})
    except Exception:
        S.delete([path])
        raise


def actualizar_posicion(plantilla_id: int, pagina: int | None, x: float, y: float, ancho: float) -> None:
    execute_write("""
        UPDATE operational.doc_plantillas
        SET firma_pagina = :pg, firma_x = :x, firma_y = :y, firma_ancho = :a
        WHERE plantilla_id = :id
    """, {"id": int(plantilla_id), "pg": pagina, "x": x, "y": y, "a": ancho})


# =============================================================================
# Carpetas automaticas  Contratos / PLACA / CONTRATO
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


def carpeta_contrato(placa: str, contrato: int, usuario: str) -> int:
    raiz = _carpeta(CARPETA_RAIZ, None, usuario)
    cp = _carpeta(placa, raiz, usuario)
    return _carpeta(str(int(contrato)), cp, usuario)


# =============================================================================
# Expedientes
# =============================================================================
def expediente(contrato: int) -> dict | None:
    df = D.load_query("SELECT * FROM operational.doc_contratos WHERE contrato = :c", {"c": int(contrato)})
    return None if df.empty else df.iloc[0].to_dict()


def documentos_contrato(contrato: int) -> pd.DataFrame:
    return D.load_query("""
        SELECT d.documento_id, d.tipo_documento, d.nombre, d.storage_path, d.mime_type,
               d.tamano_bytes, d.subido_por, d.subido_at, d.firmado_de, d.firmado_por,
               d.firmado_at, d.contrato, d.placas, d.firma_pagina, d.carpeta_id,
               p.version AS plantilla_version
        FROM operational.documentos d
        LEFT JOIN operational.doc_plantillas p ON p.plantilla_id = d.plantilla_id
        WHERE d.contrato = :c AND NOT d.eliminado AND d.tipo_documento IS NOT NULL
        ORDER BY CASE d.tipo_documento WHEN 'CONTRATO' THEN 1 WHEN 'ADENDUM' THEN 2
                                       WHEN 'INFO_GENERAL' THEN 3 ELSE 4 END
    """, {"c": int(contrato)})


def contratos_de_placa(placa: str) -> pd.DataFrame:
    """Expedientes cuya placa digitada es `placa` o cuyo contrato (segun el sistema)
    tuvo esa placa en algun tramo."""
    return D.load_query("""
        SELECT e.contrato, e.placa, e.creado_por, e.creado_at,
               COUNT(d.documento_id) FILTER (WHERE d.firmado_por IS NOT NULL
                   AND d.tipo_documento IN ('CONTRATO','ADENDUM','INFO_GENERAL')) AS firmados,
               MAX(d.subido_at) AS ultima_carga
        FROM operational.doc_contratos e
        LEFT JOIN operational.documentos d
               ON d.contrato = e.contrato AND NOT d.eliminado AND d.tipo_documento IS NOT NULL
        WHERE e.placa = :p
           OR EXISTS (SELECT 1 FROM operational.documentos x
                      WHERE x.contrato = e.contrato AND NOT x.eliminado AND :p = ANY(x.placas))
        GROUP BY e.contrato, e.placa, e.creado_por, e.creado_at
        ORDER BY e.creado_at DESC
    """, {"p": placa})


def preparar(contrato_pdf: bytes, firma: dict, pos_contrato: dict, leyenda: str,
             plantillas: pd.DataFrame, bytes_de) -> list[dict]:
    """Estampa la firma en el contrato y en cada plantilla activa. No guarda nada.
    pos_contrato = {pagina (0-based), x, y, ancho}. bytes_de(path) -> bytes (cache de la pagina).
    Devuelve [{tipo, firmado (bytes), pagina (0-based), plantilla_id, original}]."""
    out = [{
        "tipo": "CONTRATO", "original": contrato_pdf, "plantilla_id": None,
        "pagina": pos_contrato["pagina"],
        "firmado": D.estampar_firma(contrato_pdf, firma, pos_contrato["pagina"], pos_contrato["x"],
                                    pos_contrato["y"], pos_contrato["ancho"], leyenda),
    }]
    for p in plantillas.itertuples():
        data = bytes_de(p.storage_path)
        n = len(D.info_pdf(data))
        pg = (int(p.firma_pagina) - 1) if pd.notna(p.firma_pagina) else n - 1
        pg = min(max(pg, 0), n - 1)
        out.append({"tipo": p.tipo, "original": data, "plantilla_id": int(p.plantilla_id), "pagina": pg,
                    "firmado": D.estampar_firma(data, firma, pg, p.firma_x, p.firma_y, p.firma_ancho, leyenda)})
    return out


def guardar(contrato: int, placa: str, preparados: list[dict], usuario: str,
            sede: str | None = None) -> dict:
    """Guarda el expediente: el contrato SIN firmar (traza) + los 3 firmados, en la
    carpeta Contratos/PLACA/CONTRATO. Si ya existia un documento vigente del mismo
    tipo se reemplaza (el viejo queda eliminado). Devuelve {tipo: documento_id}."""
    contrato = int(contrato)
    exp = expediente(contrato)
    if exp and exp["placa"] != placa:
        raise ValueError(f"El contrato {contrato} ya tiene expediente con la placa {exp['placa']}. "
                         "Corrige la placa desde Validación antes de volver a firmar.")
    carpeta = carpeta_contrato(placa, contrato, usuario)
    info = D.info_contrato(contrato) or {"contrato": contrato, "placas": [], "sede": sede}
    execute_write("""
        INSERT INTO operational.doc_contratos (contrato, placa, sede_nombre, creado_por)
        VALUES (:c, :p, :s, :u)
        ON CONFLICT (contrato) DO UPDATE
            SET actualizado_por = :u, actualizado_at = now(),
                sede_nombre = COALESCE(EXCLUDED.sede_nombre, operational.doc_contratos.sede_nombre)
    """, {"c": contrato, "p": placa, "s": info.get("sede") or sede, "u": usuario})

    ids = {}
    prefijo = f"contratos/{contrato}"
    for item in preparados:
        tipo = item["tipo"]
        execute_write("""
            UPDATE operational.documentos
            SET eliminado = TRUE, eliminado_por = :u, eliminado_at = now()
            WHERE contrato = :c AND tipo_documento IN (:t, :t || '_SIN_FIRMA') AND NOT eliminado
        """, {"c": contrato, "t": tipo, "u": usuario})
        orig_id = None
        if tipo == "CONTRATO":   # el contrato tal como lo subio el asesor, sin firma
            orig_id = D.subir(carpeta, nombre_archivo(contrato, placa, tipo, firmado=False),
                              item["original"], "application/pdf", usuario,
                              contrato=info, tipo_documento="CONTRATO_SIN_FIRMA", path_prefix=prefijo)
        ids[tipo] = D.subir(carpeta, nombre_archivo(contrato, placa, tipo), item["firmado"],
                            "application/pdf", usuario, contrato=info,
                            firmado_de=orig_id if orig_id else None,
                            firma_pagina=item["pagina"] + 1, tipo_documento=tipo,
                            plantilla_id=item["plantilla_id"], path_prefix=prefijo)
        if orig_id is None:      # plantillas: marcar como firmado aunque no haya "original" propio
            execute_write("""
                UPDATE operational.documentos SET firmado_por = :u, firmado_at = now()
                WHERE documento_id = :id
            """, {"id": ids[tipo], "u": usuario})
    return ids


def corregir_placa(contrato: int, placa_nueva: str, usuario: str) -> None:
    """Cambia la placa del expediente: mueve los documentos a Contratos/<nueva>/<contrato>
    y renombra. Los objetos de Storage no se mueven (su ruta no lleva la placa)."""
    exp = expediente(contrato)
    if not exp:
        raise ValueError("Ese contrato no tiene expediente.")
    vieja = exp["placa"]
    carpeta = carpeta_contrato(placa_nueva, contrato, usuario)
    execute_write("""
        UPDATE operational.documentos
        SET carpeta_id = :cp, nombre = replace(nombre, :sv, :sn)
        WHERE contrato = :c AND tipo_documento IS NOT NULL;
        UPDATE operational.doc_contratos
        SET placa = :pn, actualizado_por = :u, actualizado_at = now()
        WHERE contrato = :c
    """, {"c": int(contrato), "cp": carpeta, "sv": f"_{vieja}_", "sn": f"_{placa_nueva}_",
          "pn": placa_nueva, "u": usuario})


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
    """Una fila por contrato: los expedientes creados en el rango + los contratos del
    sistema entregados en el rango (desde FECHA_INICIO) que no tienen expediente.
    Columnas: contrato, placa_digitada, placas_sistema, sede, entrega, creado_por,
    creado_at, faltan, estado (clave de ESTADOS)."""
    d0 = max(desde, FECHA_INICIO)
    exp = D.load_query("""
        SELECT e.contrato, e.placa AS placa_digitada, e.sede_nombre, e.creado_por, e.creado_at,
               COALESCE(array_agg(DISTINCT d.tipo_documento)
                        FILTER (WHERE d.tipo_documento IS NOT NULL), '{}') AS tipos
        FROM operational.doc_contratos e
        LEFT JOIN operational.documentos d
               ON d.contrato = e.contrato AND NOT d.eliminado AND d.firmado_por IS NOT NULL
        WHERE (e.creado_at AT TIME ZONE 'America/Bogota')::date BETWEEN :d AND :h
        GROUP BY 1, 2, 3, 4, 5
    """, {"d": desde, "h": hasta})
    sis = D.load_query("""
        SELECT numero_contrato::bigint AS contrato, TRIM(placa) AS placa, sede_handover,
               fecha_handover_real::date AS entrega
        FROM silver.vw_rentals_full
        WHERE fecha_handover_real::date BETWEEN :d AND :h
          AND TRIM(COALESCE(placa, '')) <> '' AND COALESCE(revenue_total_usd, 0) > 0
    """, {"d": d0, "h": hasta}) if d0 <= hasta else pd.DataFrame(
        columns=["contrato", "placa", "sede_handover", "entrega"])
    # datos del sistema para los expedientes (aunque su entrega caiga fuera del rango)
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
    placas = {}
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
        sede = hdr.at[c, "sede_handover"] if en_sis else (e.sede_nombre if e is not None else None)
        fila = {"contrato": c, "placa_digitada": e.placa_digitada if e is not None else "",
                "placas_sistema": ", ".join(pls), "sede": sede,
                "entrega": hdr.at[c, "entrega"] if en_sis else None,
                "creado_por": e.creado_por if e is not None else "",
                "creado_at": e.creado_at if e is not None else None, "faltan": ""}
        if e is None:
            fila["estado"] = "SIN_DOCS"
            fila["faltan"] = ", ".join(TIPOS[t] for t in TIPOS_REQUERIDOS)
        else:
            tipos = set(e.tipos or [])
            faltan = [TIPOS[t] for t in TIPOS_REQUERIDOS if t not in tipos]
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
