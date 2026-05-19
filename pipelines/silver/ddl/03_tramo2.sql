-- =============================================================================
-- SILVER - TRAMO 2 - tablas operativas propias de Trust (Postgres)
-- =============================================================================
-- Trust captura estas por su lado (formularios, scripts, app movil).
-- NO vienen de Sixt y NO se rebuildan en cada corrida (CREATE TABLE IF NOT EXISTS,
-- sin DROP).
-- =============================================================================


-- -----------------------------------------------------------------------------
-- 1. Cierre diario de sede
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.op_cierre_diario_sede (
    cier_id                       BIGSERIAL PRIMARY KEY,
    brnc_code                     INTEGER NOT NULL,
    cier_date                     DATE NOT NULL,
    cier_dtid                     INTEGER,
    cier_submitted_flg            INTEGER DEFAULT 0,
    cier_submitted_datm           TIMESTAMPTZ,
    cier_submitted_by             INTEGER,
    cier_rentals_count            INTEGER DEFAULT 0,
    cier_returns_count            INTEGER DEFAULT 0,
    cier_revenue_total            NUMERIC(14,2) DEFAULT 0,
    cier_cash_collected           NUMERIC(14,2) DEFAULT 0,
    cier_card_collected           NUMERIC(14,2) DEFAULT 0,
    cier_vehicles_in_branch       INTEGER DEFAULT 0,
    cier_vehicles_available       INTEGER DEFAULT 0,
    cier_vehicles_rented          INTEGER DEFAULT 0,
    cier_vehicles_maintenance     INTEGER DEFAULT 0,
    cier_vehicles_blocked         INTEGER DEFAULT 0,
    cier_pending_returns_next_day INTEGER DEFAULT 0,
    cier_observations             TEXT,
    cier_status                   TEXT DEFAULT 'PENDING'
);


-- -----------------------------------------------------------------------------
-- 2. Novedades de vehiculos
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.op_novedades_vehiculo (
    nove_id               BIGSERIAL PRIMARY KEY,
    nove_date             DATE NOT NULL,
    nove_datm             TIMESTAMPTZ,
    brnc_code             INTEGER,
    vhcl_int_num          INTEGER,
    vhcl_plate            TEXT,
    nove_type             TEXT,
    nove_severity         TEXT,
    nove_description      TEXT,
    nove_reported_by      INTEGER,
    nove_status           TEXT DEFAULT 'ABIERTA',
    nove_resolved_datm    TIMESTAMPTZ,
    nove_resolution_notes TEXT
);


-- -----------------------------------------------------------------------------
-- 3. Incidentes
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.op_incidentes (
    inci_id              BIGSERIAL PRIMARY KEY,
    inci_date            DATE NOT NULL,
    inci_datm            TIMESTAMPTZ,
    brnc_code            INTEGER,
    vhcl_int_num         INTEGER,
    rntl_mvnr            BIGINT,
    cstm_kdnr            BIGINT,
    inci_type            TEXT,
    inci_severity        TEXT,
    inci_description     TEXT,
    inci_third_party_flg INTEGER DEFAULT 0,
    inci_police_flg      INTEGER DEFAULT 0,
    inci_insurance_flg   INTEGER DEFAULT 0,
    inci_estimated_cost  NUMERIC(14,2),
    inci_status          TEXT DEFAULT 'ABIERTO',
    inci_reported_by     INTEGER,
    inci_assigned_to     INTEGER
);


-- -----------------------------------------------------------------------------
-- 4. Checklist apertura/cierre de sede
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.op_checklist_apertura_cierre (
    chkl_id                       BIGSERIAL PRIMARY KEY,
    chkl_date                     DATE NOT NULL,
    chkl_dtid                     INTEGER,
    brnc_code                     INTEGER NOT NULL,
    chkl_type                     TEXT,
    chkl_datm                     TIMESTAMPTZ,
    chkl_submitted_by             INTEGER,
    chkl_caja_ok                  INTEGER,
    chkl_caja_monto               NUMERIC(14,2),
    chkl_oficina_limpia           INTEGER,
    chkl_inventario_vehiculos_ok  INTEGER,
    chkl_documentos_organizados   INTEGER,
    chkl_sistema_operativo_ok     INTEGER,
    chkl_seguridad_ok             INTEGER,
    chkl_combustible_disponible   INTEGER,
    chkl_observations             TEXT,
    chkl_score                    INTEGER,
    chkl_status                   TEXT DEFAULT 'COMPLETO'
);


-- -----------------------------------------------------------------------------
-- 5. Traslado de vehiculos inter-sede
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.op_traslado_vehiculos (
    tras_id                BIGSERIAL PRIMARY KEY,
    tras_request_date      DATE NOT NULL,
    tras_request_datm      TIMESTAMPTZ,
    vhcl_int_num           INTEGER NOT NULL,
    vhcl_plate             TEXT,
    brnc_code_origin       INTEGER,
    brnc_code_destination  INTEGER,
    tras_reason            TEXT,
    tras_priority          TEXT,
    tras_requested_by      INTEGER,
    tras_assigned_to       INTEGER,
    tras_executed_datm     TIMESTAMPTZ,
    tras_arrival_datm      TIMESTAMPTZ,
    tras_distance_km       INTEGER,
    tras_duration_hours    NUMERIC(8,2),
    tras_cost              NUMERIC(14,2),
    tras_status            TEXT DEFAULT 'SOLICITADO',
    tras_observations      TEXT
);


-- -----------------------------------------------------------------------------
-- 6. Solicitudes de soporte
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.op_solicitudes_soporte (
    sopt_id               BIGSERIAL PRIMARY KEY,
    sopt_request_date     DATE NOT NULL,
    sopt_request_datm     TIMESTAMPTZ,
    brnc_code             INTEGER,
    sopt_category         TEXT,
    sopt_priority         TEXT,
    sopt_subject          TEXT,
    sopt_description      TEXT,
    sopt_requested_by     INTEGER,
    sopt_assigned_to      INTEGER,
    sopt_status           TEXT DEFAULT 'ABIERTO',
    sopt_resolved_datm    TIMESTAMPTZ,
    sopt_sla_hours        INTEGER DEFAULT 24,
    sopt_sla_breach_flg   INTEGER DEFAULT 0,
    sopt_resolution_notes TEXT
);


-- -----------------------------------------------------------------------------
-- 7. Contratos con soportes faltantes
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.op_contratos_soportes_faltantes (
    cosf_id             BIGSERIAL PRIMARY KEY,
    cosf_date           DATE NOT NULL,
    rntl_mvnr           BIGINT,
    rsrv_resn           BIGINT,
    cstm_kdnr           BIGINT,
    brnc_code           INTEGER,
    cosf_missing_type   TEXT,
    cosf_missing_count  INTEGER DEFAULT 1,
    cosf_severity       TEXT,
    cosf_age_hours      INTEGER,
    cosf_age_days       INTEGER,
    cosf_status         TEXT DEFAULT 'PENDIENTE',
    cosf_responsible    INTEGER,
    cosf_resolved_datm  TIMESTAMPTZ,
    cosf_observations   TEXT
);


-- Indices op_*
CREATE INDEX IF NOT EXISTS idx_op_cier_brnc_date ON silver.op_cierre_diario_sede(brnc_code, cier_date);
CREATE INDEX IF NOT EXISTS idx_op_nove_date      ON silver.op_novedades_vehiculo(nove_date);
CREATE INDEX IF NOT EXISTS idx_op_inci_date      ON silver.op_incidentes(inci_date);
CREATE INDEX IF NOT EXISTS idx_op_chkl_date      ON silver.op_checklist_apertura_cierre(chkl_date);
CREATE INDEX IF NOT EXISTS idx_op_tras_date      ON silver.op_traslado_vehiculos(tras_request_date);
CREATE INDEX IF NOT EXISTS idx_op_sopt_date      ON silver.op_solicitudes_soporte(sopt_request_date);
CREATE INDEX IF NOT EXISTS idx_op_cosf_date      ON silver.op_contratos_soportes_faltantes(cosf_date);
