-- =============================================================================
-- SILVER - HECHOS (Postgres)
-- =============================================================================
-- Rebuild completo cada corrida (DROP + CREATE AS SELECT desde bronze).
-- Mantenemos todas las columnas de Bronze para no perder informacion.
-- =============================================================================


DROP TABLE IF EXISTS silver.fact_reservations CASCADE;
CREATE TABLE silver.fact_reservations AS
SELECT * FROM bronze.rent_shop_rs_fct_reservations;
CREATE INDEX IF NOT EXISTS idx_fact_reservations_resn          ON silver.fact_reservations(rsrv_resn);
CREATE INDEX IF NOT EXISTS idx_fact_reservations_brnc_handover ON silver.fact_reservations(brnc_code_handover);
CREATE INDEX IF NOT EXISTS idx_fact_reservations_brnc_return   ON silver.fact_reservations(brnc_code_return);
CREATE INDEX IF NOT EXISTS idx_fact_reservations_kdnr          ON silver.fact_reservations(cstm_kdnr);
CREATE INDEX IF NOT EXISTS idx_fact_reservations_handover_date ON silver.fact_reservations(rsrv_handover_date);


DROP TABLE IF EXISTS silver.fact_rentals CASCADE;
CREATE TABLE silver.fact_rentals AS
SELECT * FROM bronze.rent_shop_ra_fct_rentals_vwt_franchise;
CREATE INDEX IF NOT EXISTS idx_fact_rentals_mvnr          ON silver.fact_rentals(rntl_mvnr);
CREATE INDEX IF NOT EXISTS idx_fact_rentals_brnc_handover ON silver.fact_rentals(brnc_code_handover);
CREATE INDEX IF NOT EXISTS idx_fact_rentals_handover_date ON silver.fact_rentals(rntl_handover_date);
CREATE INDEX IF NOT EXISTS idx_fact_rentals_return_date   ON silver.fact_rentals(rntl_return_date);


DROP TABLE IF EXISTS silver.fact_rental_vehicles CASCADE;
CREATE TABLE silver.fact_rental_vehicles AS
SELECT * FROM bronze.rent_shop_ra_fct_rental_vehicles_franchise;
CREATE INDEX IF NOT EXISTS idx_fact_rental_vehicles_mvnr    ON silver.fact_rental_vehicles(rntl_mvnr);
CREATE INDEX IF NOT EXISTS idx_fact_rental_vehicles_int_num ON silver.fact_rental_vehicles(vhcl_int_num);


DROP TABLE IF EXISTS silver.fact_charges_rs CASCADE;
CREATE TABLE silver.fact_charges_rs AS
SELECT * FROM bronze.rent_shop_ch_fct_rs_charges_franchise;
CREATE INDEX IF NOT EXISTS idx_fact_charges_rs_resn ON silver.fact_charges_rs(chrs_resn);


DROP TABLE IF EXISTS silver.fact_charges_ra CASCADE;
CREATE TABLE silver.fact_charges_ra AS
SELECT * FROM bronze.rent_shop_ch_fct_ra_charges_franchise;
CREATE INDEX IF NOT EXISTS idx_fact_charges_ra_mvnr ON silver.fact_charges_ra(chra_mvnr);


DROP TABLE IF EXISTS silver.fact_damages CASCADE;
CREATE TABLE silver.fact_damages AS
SELECT * FROM bronze.damage_shop_dm_fct_damages;


DROP TABLE IF EXISTS silver.fact_damage_details CASCADE;
CREATE TABLE silver.fact_damage_details AS
SELECT * FROM bronze.damage_shop_dm_fct_damage_details_franchise;


DROP TABLE IF EXISTS silver.fact_damage_cases CASCADE;
CREATE TABLE silver.fact_damage_cases AS
SELECT * FROM bronze.damage_shop_dm_dim_damage_cases_franchise;


-- =============================================================================
-- PLACEHOLDER - fact que el dashboard demo usa pero Sixt no comparte
-- =============================================================================

DROP TABLE IF EXISTS silver.fact_payments CASCADE;
CREATE TABLE silver.fact_payments (
    paym_id        BIGSERIAL PRIMARY KEY,
    mndt_code      INTEGER NOT NULL,
    paym_resn      BIGINT,
    paym_mvnr      BIGINT,
    paym_type      TEXT,
    paym_method    TEXT,
    paym_amount    NUMERIC(14,2),
    paym_currency  TEXT DEFAULT 'COP',
    paym_date      DATE,
    paym_status    TEXT DEFAULT 'COMPLETED'
);
