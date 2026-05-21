-- =============================================================================
-- SILVER - DIMENSIONES (Postgres)
-- =============================================================================
-- Lee desde bronze.* (mismo Supabase, schema separado) y reconstruye dim_* en
-- silver. Estrategia: rebuild completo cada corrida (DROP + CREATE AS SELECT).
-- La historia SCD2 que importa ya viene de Sixt en las tablas que la traen
-- (`ve_fct_vehicles_current_incl_history`, `rt_dim_rates_franchise` con
-- `rate_gdat`). NO versionamos local.
-- =============================================================================


-- -----------------------------------------------------------------------------
-- dim_branches (sedes) - 6 filas para Trust CO
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS silver.dim_branches CASCADE;
CREATE TABLE silver.dim_branches AS
SELECT * FROM bronze.common_shop_br_dim_branches;
CREATE INDEX IF NOT EXISTS idx_dim_branches_code ON silver.dim_branches(brnc_code);


-- -----------------------------------------------------------------------------
-- dim_mandants (1 fila, mandant 409 = Colombia)
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS silver.dim_mandants CASCADE;
CREATE TABLE silver.dim_mandants AS
SELECT * FROM bronze.common_shop_mn_dim_mandants;


-- -----------------------------------------------------------------------------
-- dim_vehicle_groups (ACRISS codes, 13 filas)
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS silver.dim_vehicle_groups CASCADE;
CREATE TABLE silver.dim_vehicle_groups AS
SELECT * FROM bronze.fleet_shop_ve_dim_vehicle_groups_franchise;
CREATE INDEX IF NOT EXISTS idx_dim_vehicle_groups_crs ON silver.dim_vehicle_groups(vhgr_crs);


-- -----------------------------------------------------------------------------
-- dim_vehicle_models (72k filas globales)
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS silver.dim_vehicle_models CASCADE;
CREATE TABLE silver.dim_vehicle_models AS
SELECT * FROM bronze.fleet_shop_ve_dim_vehicle_models;
CREATE INDEX IF NOT EXISTS idx_dim_vehicle_models_cdef ON silver.dim_vehicle_models(vhmd_cdef);


-- -----------------------------------------------------------------------------
-- dim_vehicles (master, 183 filas)
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS silver.dim_vehicles CASCADE;
CREATE TABLE silver.dim_vehicles AS
SELECT * FROM bronze.fleet_shop_ve_dim_vehicles;
CREATE INDEX IF NOT EXISTS idx_dim_vehicles_int_num ON silver.dim_vehicles(vhcl_int_num);


-- -----------------------------------------------------------------------------
-- dim_vehicles_current (snapshot estado actual, 106 filas activas)
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS silver.dim_vehicles_current CASCADE;
CREATE TABLE silver.dim_vehicles_current AS
SELECT * FROM bronze.fleet_shop_ve_fct_vehicles_current;
CREATE INDEX IF NOT EXISTS idx_dim_vehicles_current_int_num ON silver.dim_vehicles_current(vhcl_int_num);


-- -----------------------------------------------------------------------------
-- dim_vehicles_history (incl_history, 183 filas — historia desde Sixt)
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS silver.dim_vehicles_history CASCADE;
CREATE TABLE silver.dim_vehicles_history AS
SELECT * FROM bronze.fleet_shop_ve_fct_vehicles_current_incl_history;
CREATE INDEX IF NOT EXISTS idx_dim_vehicles_history_int_num ON silver.dim_vehicles_history(vhcl_int_num);


-- -----------------------------------------------------------------------------
-- dim_partners (B2B KDNRs corporativos, 902 filas)
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS silver.dim_partners CASCADE;
CREATE TABLE silver.dim_partners AS
SELECT * FROM bronze.customer_shop_pa_dim_partners_franchise;
CREATE INDEX IF NOT EXISTS idx_dim_partners_kdnr ON silver.dim_partners(prtn_kdnr);


-- -----------------------------------------------------------------------------
-- dim_agencies (651 filas)
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS silver.dim_agencies CASCADE;
CREATE TABLE silver.dim_agencies AS
SELECT * FROM bronze.customer_shop_pa_dim_agencies_franchise;


-- -----------------------------------------------------------------------------
-- dim_rate_plans (1,434 filas con SCD2 implicito por rate_gdat)
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS silver.dim_rate_plans CASCADE;
CREATE TABLE silver.dim_rate_plans AS
SELECT * FROM bronze.rent_shop_rt_dim_rates_franchise;
CREATE INDEX IF NOT EXISTS idx_dim_rate_plans_prl ON silver.dim_rate_plans(rate_prl);


-- -----------------------------------------------------------------------------
-- dim_channels_rs (canal SCD asociado a reservas, 27k filas)
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS silver.dim_channels_rs CASCADE;
CREATE TABLE silver.dim_channels_rs AS
SELECT * FROM bronze.rent_shop_rs_dim_scd_channels_franchise;
CREATE INDEX IF NOT EXISTS idx_dim_channels_rs_resn ON silver.dim_channels_rs(rsrv_resn);


-- -----------------------------------------------------------------------------
-- dim_channels_ra (canal SCD asociado a rentals, 14k filas)
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS silver.dim_channels_ra CASCADE;
CREATE TABLE silver.dim_channels_ra AS
SELECT * FROM bronze.rent_shop_ra_dim_scd_channels_franchise;
CREATE INDEX IF NOT EXISTS idx_dim_channels_ra_mvnr ON silver.dim_channels_ra(rntl_mvnr);


-- =============================================================================
-- PLACEHOLDERS - tablas que el dashboard demo espera pero Sixt NO comparte
-- =============================================================================

DROP TABLE IF EXISTS silver.dim_customers CASCADE;
CREATE TABLE silver.dim_customers (
    cstm_kdnr              BIGINT PRIMARY KEY,
    mndt_code              INTEGER,
    cstm_first_name        TEXT,
    cstm_last_name         TEXT,
    cstm_full_name         TEXT,
    cstm_doc_type          TEXT,
    cstm_doc_number        TEXT,
    cstm_email             TEXT,
    cstm_phone             TEXT,
    cstm_country           TEXT,
    cstm_city              TEXT,
    cstm_loyalty_tier      TEXT,
    cstm_corporate_flg     INTEGER DEFAULT 0,
    cstm_blacklist_flg     INTEGER DEFAULT 0,
    cstm_first_rental_date DATE,
    cstm_total_rentals     INTEGER DEFAULT 0
);


DROP TABLE IF EXISTS silver.dim_employees CASCADE;
CREATE TABLE silver.dim_employees (
    empl_id          BIGSERIAL PRIMARY KEY,
    mndt_code        INTEGER,
    brnc_code        INTEGER,
    empl_name        TEXT,
    empl_role        TEXT,
    empl_email       TEXT,
    empl_active_flg  INTEGER DEFAULT 1
);


-- dim_dates: calendario estatico 2020-2030. NO se dropea cada rebuild
-- (es deterministica, no depende de bronze). build_dim_dates() en build.py
-- detecta si ya esta poblada y hace skip; si no, la llena.
CREATE TABLE IF NOT EXISTS silver.dim_dates (
    dtid           INTEGER PRIMARY KEY,
    full_date      DATE,
    year           INTEGER,
    month          INTEGER,
    month_name     TEXT,
    day            INTEGER,
    day_of_week    INTEGER,
    day_name       TEXT,
    week_of_year   INTEGER,
    quarter        INTEGER,
    is_weekend     INTEGER,
    is_holiday_co  INTEGER DEFAULT 0,
    holiday_name   TEXT
);
CREATE INDEX IF NOT EXISTS idx_dim_dates_full_date ON silver.dim_dates(full_date);
