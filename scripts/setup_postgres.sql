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
    rntl_mvnr         BIGINT,                      -- numero_contrato del rental
    rsrv_resn         BIGINT,                      -- numero de reserva (opcional)
    sede_codigo       INTEGER,                     -- brnc_code
    sede_nombre       TEXT,
    fecha_emision     DATE NOT NULL,
    forma_pago        TEXT,                        -- EFECTIVO / TARJETA / TRANSFERENCIA
    moneda            TEXT NOT NULL DEFAULT 'COP', -- 'COP' o 'USD'
    monto_base        NUMERIC(14,2),
    iva               NUMERIC(14,2),
    monto_total       NUMERIC(14,2) NOT NULL,
    numero_documento  TEXT,                        -- referencia interna / consecutivo
    observaciones     TEXT,
    capturado_por     TEXT,                        -- usuario que llenó el form
    capturado_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_invoices_fecha   ON operational.invoices (fecha_emision DESC);
CREATE INDEX IF NOT EXISTS idx_invoices_rntl    ON operational.invoices (rntl_mvnr);
CREATE INDEX IF NOT EXISTS idx_invoices_sede    ON operational.invoices (sede_codigo, fecha_emision);

COMMENT ON TABLE operational.invoices IS 'Facturas/recibos capturados por el form del dashboard.';

-- 4. Sanidad / verificacion
-- Al terminar este script deberian existir:
--   bronze, silver, operational schemas
--   bronze.ctrl_extraction_log
--   operational.invoices
-- y ningun dato silver todavia (eso lo crea pipelines/silver/build.py en su primera corrida).
