-- =============================================================================
-- SILVER - VIEWS (Postgres)
-- =============================================================================
-- Vistas derivadas que ofrecen agregaciones / pre-joins para el dashboard.
-- vw_cierre_diario_sede se materializa como TABLA en silver/build.py.
-- =============================================================================


-- -----------------------------------------------------------------------------
-- vw_reservation_enriched: pre-join reserva + sede + grupo vehiculo
-- -----------------------------------------------------------------------------
DROP VIEW IF EXISTS silver.vw_reservation_enriched CASCADE;
CREATE VIEW silver.vw_reservation_enriched AS
SELECT
    r.rsrv_resn,
    r.mndt_code,
    r.brnc_code_handover,
    bh.brnc_name                  AS brnc_name_handover,
    bh.brnc_city                  AS brnc_city_handover,
    r.brnc_code_return,
    br.brnc_name                  AS brnc_name_return,
    r.cstm_kdnr,
    r.vhgr_crs,
    vg.vhgr_category_level1,
    vg.vhgr_category_level2,
    r.rsrv_status,
    r.rsrv_status_extended,
    r.rsrv_date,
    r.rsrv_handover_date,
    r.rsrv_handover_datm,
    r.rsrv_return_date,
    r.rsrv_return_datm,
    r.rsrv_prepaid_value_local        AS rsrv_prepaid_value
FROM silver.fact_reservations r
LEFT JOIN silver.dim_branches bh         ON bh.brnc_code = r.brnc_code_handover
LEFT JOIN silver.dim_branches br         ON br.brnc_code = r.brnc_code_return
LEFT JOIN silver.dim_vehicle_groups vg   ON vg.vhgr_crs  = r.vhgr_crs;


-- -----------------------------------------------------------------------------
-- vw_vehicle_current_state: snapshot del estado actual de cada vehiculo
-- -----------------------------------------------------------------------------
DROP VIEW IF EXISTS silver.vw_vehicle_current_state CASCADE;
CREATE VIEW silver.vw_vehicle_current_state AS
SELECT
    vc.vhcl_int_num,
    vc.brnc_code,
    b.brnc_name                   AS brnc_name,
    b.brnc_city                   AS brnc_city,
    v.vhgr_crs,
    vg.vhgr_category_level1,
    vg.vhgr_category_level2,
    vc.vhcl_on_rent_flg,
    vc.vhcl_ready_to_rent_flg,
    vc.vhcl_pickup_date,
    vc.vhcl_return_date
FROM silver.dim_vehicles_current vc
LEFT JOIN silver.dim_branches b          ON b.brnc_code = vc.brnc_code
LEFT JOIN silver.dim_vehicles v          ON v.vhcl_int_num = vc.vhcl_int_num
LEFT JOIN silver.dim_vehicle_groups vg   ON vg.vhgr_crs = v.vhgr_crs;


-- -----------------------------------------------------------------------------
-- vw_ranking_sedes: ranking ejecutivo por sede (con CTEs separadas).
-- -----------------------------------------------------------------------------
DROP VIEW IF EXISTS silver.vw_ranking_sedes CASCADE;
CREATE VIEW silver.vw_ranking_sedes AS
WITH rentals_per_branch AS (
    SELECT brnc_code_handover AS brnc_code, COUNT(*) AS rentals_total
    FROM silver.fact_rentals
    GROUP BY brnc_code_handover
),
revenue_per_branch AS (
    SELECT r.brnc_code_handover AS brnc_code, SUM(c.chra_value_local) AS revenue_total
    FROM silver.fact_rentals r
    LEFT JOIN silver.fact_charges_ra c ON c.chra_mvnr = r.rntl_mvnr
    GROUP BY r.brnc_code_handover
),
fleet_per_branch AS (
    SELECT brnc_code,
           COUNT(*) AS vehicles_in_branch,
           SUM(CASE WHEN vhcl_on_rent_flg = 1 THEN 1 ELSE 0 END) AS vehicles_rented
    FROM silver.dim_vehicles_current
    GROUP BY brnc_code
)
SELECT
    b.brnc_code,
    b.brnc_name,
    b.brnc_city,
    b.brnc_main_type,
    COALESCE(r.rentals_total, 0)             AS rentals_total,
    COALESCE(rev.revenue_total, 0)           AS revenue_total,
    COALESCE(f.vehicles_in_branch, 0)        AS vehicles_in_branch,
    COALESCE(f.vehicles_rented, 0)           AS vehicles_rented,
    CASE
        WHEN COALESCE(f.vehicles_in_branch, 0) = 0 THEN 0.0
        ELSE 100.0 * f.vehicles_rented / f.vehicles_in_branch
    END                                      AS occupancy_pct
FROM silver.dim_branches b
LEFT JOIN rentals_per_branch r   ON r.brnc_code = b.brnc_code
LEFT JOIN revenue_per_branch rev ON rev.brnc_code = b.brnc_code
LEFT JOIN fleet_per_branch f     ON f.brnc_code = b.brnc_code;
