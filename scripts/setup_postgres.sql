-- =============================================================================
-- Trust Data Platform - bootstrap de Supabase Postgres
-- =============================================================================
-- Corre este script UNA sola vez contra una Supabase nueva:
--
--   psql "$SUPABASE_DB_URL" -f scripts/setup_postgres.sql
--
-- Crea los schemas bronze / silver / operational, las tablas de control de
-- pipeline (ctrl_extraction_log, operational.invoices), e inicializa search_path
-- por defecto para el rol postgres.
-- =============================================================================

-- 1. Schemas
CREATE SCHEMA IF NOT EXISTS bronze;
CREATE SCHEMA IF NOT EXISTS silver;
CREATE SCHEMA IF NOT EXISTS operational;

COMMENT ON SCHEMA bronze      IS 'Espejo crudo del datashare Sixt Redshift. Mismos nombres que en origen.';
COMMENT ON SCHEMA silver      IS 'Modelo gobernado: dim_*, fact_*, vw_* (materializados como TABLE).';
COMMENT ON SCHEMA operational IS 'Datos capturados por Trust: facturas, novedades, checklists.';

-- search_path por defecto para sesiones futuras del rol postgres.
-- silver primero, bronze segundo: queries del dashboard usan nombres no-prefijados.
ALTER DATABASE postgres SET search_path TO silver, bronze, operational, public;

-- statement_timeout: el default de Supabase (2 min) mata vw_rentals_detail
-- y otras queries grandes. Subimos a 15 min para el rol postgres (que es
-- el que usan los pipelines y el dashboard).
ALTER ROLE postgres SET statement_timeout = '15min';

-- En la sesion actual tambien, para que el resto de este script funcione sin prefijos.
SET search_path TO silver, bronze, operational, public;


-- 2. Control de pipeline (bronze.ctrl_extraction_log)
-- Antes vivia en bronze.db local; en GitHub Actions ephemeral lo necesitamos persistente.
CREATE TABLE IF NOT EXISTS bronze.ctrl_extraction_log (
    id            BIGSERIAL PRIMARY KEY,
    run_datm      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    table_name    TEXT NOT NULL,
    mode          TEXT,
    rows_loaded   BIGINT,
    watermark_to  TEXT,
    duration_sec  DOUBLE PRECISION,
    status        TEXT,
    error_detail  TEXT
);
CREATE INDEX IF NOT EXISTS idx_ctrl_extraction_table_run
    ON bronze.ctrl_extraction_log (table_name, id DESC);


-- 3. Tabla operativa: facturas / recibos capturados desde el dashboard
-- El form de Streamlit escribe aqui (lectura+escritura desde la app).
CREATE TABLE IF NOT EXISTS operational.invoices (
    invoice_id        BIGSERIAL PRIMARY KEY,
    rntl_mvnr         BIGINT,                      -- numero del contrato de renta (RA)
    rsrv_resn         BIGINT,                      -- numero de reserva (opcional, legacy)
    sede_codigo       INTEGER,                     -- brnc_code
    sede_nombre       TEXT,
    fecha_emision     DATE NOT NULL,
    moneda            TEXT NOT NULL DEFAULT 'COP', -- siempre 'COP' por ahora
    -- Numeros de referencia capturados por el counter
    numero_factura    TEXT,                        -- consecutivo DIAN
    numero_recibo     TEXT,                        -- recibo datafono / comprobante
    -- Montos: el asesor solo digita monto_total y monto_prepagado.
    -- monto_base y iva los calcula el backend (IVA hardcoded 19 %).
    -- monto_counter = monto_total - monto_prepagado.
    monto_base        NUMERIC(14,2),
    iva               NUMERIC(14,2),
    monto_total       NUMERIC(14,2) NOT NULL,
    monto_prepagado   NUMERIC(14,2) NOT NULL DEFAULT 0,
    monto_counter     NUMERIC(14,2),
    -- Flag derivado: TRUE si monto_prepagado > 0.
    prepaid           BOOLEAN NOT NULL DEFAULT FALSE,
    observaciones     TEXT,
    capturado_por     TEXT,                        -- usuario que lleno el form
    capturado_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_invoices_fecha   ON operational.invoices (fecha_emision DESC);
CREATE INDEX IF NOT EXISTS idx_invoices_rntl    ON operational.invoices (rntl_mvnr);
CREATE INDEX IF NOT EXISTS idx_invoices_sede    ON operational.invoices (sede_codigo, fecha_emision);

COMMENT ON TABLE operational.invoices IS 'Facturas/recibos capturados por el form del dashboard.';

-- 4. Tabla operativa: disponibilidad manual de vehiculos
-- El form de Streamlit (Disponibilidad Flota) escribe aqui.
CREATE TABLE IF NOT EXISTS operational.op_disponibilidad_manual (
    id              BIGSERIAL PRIMARY KEY,
    vhcl_int_num    BIGINT NOT NULL,
    placa           TEXT NOT NULL,
    fecha           DATE NOT NULL,
    estado          TEXT NOT NULL,
    nota            TEXT,
    asesor_codigo   TEXT,
    sede_codigo     INTEGER,
    created_by      TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(vhcl_int_num, fecha)
);
CREATE INDEX IF NOT EXISTS idx_op_disp_manual_sede   ON operational.op_disponibilidad_manual (sede_codigo, fecha);
CREATE INDEX IF NOT EXISTS idx_op_disp_manual_vhcl   ON operational.op_disponibilidad_manual (vhcl_int_num, fecha);

COMMENT ON TABLE operational.op_disponibilidad_manual IS 'Estados manuales de vehiculos (PYP, taller, transito, etc.) capturados desde el dashboard.';


-- 5. Sanidad / verificacion
-- Al terminar este script deberian existir:
--   bronze, silver, operational schemas
--   bronze.ctrl_extraction_log
--   operational.invoices
-- y ningun dato silver todavia (eso lo crea pipelines/silver/build.py en su primera corrida).
