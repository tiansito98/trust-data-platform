# Schema remoto - Redshift Sixt


> Generado el 2026-05-04 11:22


**Mandant filtrado:** `409`


**Tablas exploradas:** 20


## Indice


### common_shop

- [`common_shop.br_dim_branches`](#common_shop-br_dim_branches)
- [`common_shop.mn_dim_mandants`](#common_shop-mn_dim_mandants)

### customer_shop

- [`customer_shop.pa_dim_agencies_franchise`](#customer_shop-pa_dim_agencies_franchise)
- [`customer_shop.pa_dim_partners_franchise`](#customer_shop-pa_dim_partners_franchise)

### damage_shop

- [`damage_shop.dm_dim_damage_cases_franchise`](#damage_shop-dm_dim_damage_cases_franchise)
- [`damage_shop.dm_fct_damage_details_franchise`](#damage_shop-dm_fct_damage_details_franchise)
- [`damage_shop.dm_fct_damages`](#damage_shop-dm_fct_damages)

### fleet_shop

- [`fleet_shop.ve_dim_vehicle_groups_franchise`](#fleet_shop-ve_dim_vehicle_groups_franchise)
- [`fleet_shop.ve_dim_vehicle_models`](#fleet_shop-ve_dim_vehicle_models)
- [`fleet_shop.ve_dim_vehicles`](#fleet_shop-ve_dim_vehicles)
- [`fleet_shop.ve_fct_vehicles_current`](#fleet_shop-ve_fct_vehicles_current)
- [`fleet_shop.ve_fct_vehicles_current_incl_history`](#fleet_shop-ve_fct_vehicles_current_incl_history)

### rent_shop

- [`rent_shop.ch_fct_ra_charges_franchise`](#rent_shop-ch_fct_ra_charges_franchise)
- [`rent_shop.ch_fct_rs_charges_franchise`](#rent_shop-ch_fct_rs_charges_franchise)
- [`rent_shop.ra_dim_scd_channels_franchise`](#rent_shop-ra_dim_scd_channels_franchise)
- [`rent_shop.ra_fct_rental_vehicles_franchise`](#rent_shop-ra_fct_rental_vehicles_franchise)
- [`rent_shop.ra_fct_rentals_vwt_franchise`](#rent_shop-ra_fct_rentals_vwt_franchise)
- [`rent_shop.rs_dim_scd_channels_franchise`](#rent_shop-rs_dim_scd_channels_franchise)
- [`rent_shop.rs_fct_reservations`](#rent_shop-rs_fct_reservations)
- [`rent_shop.rt_dim_rates_franchise`](#rent_shop-rt_dim_rates_franchise)

## `common_shop.br_dim_branches`

**Filas para mandant 409:** 6

**Columnas timestamp (candidatos watermark):** `brnc_opening_date, brnc_closing_date, brnc_changing_date, brnc_xpress_enabled_timestamp, brnc_xpress_disabled_timestamp, sys_ins_datm, sys_upd_datm`

**Posibles PK:** `brnc_code, mndt_code, brnc_network_code`


### Columnas (131)

| # | Columna | Tipo | Nullable | Max len |
|---|---|---|---|---|
| 1 | `brnc_code` | `integer` | YES | nan |
| 2 | `mndt_code` | `integer` | YES | nan |
| 3 | `brnc_name` | `character varying(90)` | YES | 90 |
| 4 | `brnc_code_pqi_parent` | `integer` | YES | nan |
| 5 | `brnc_relevant_flg` | `integer` | YES | nan |
| 6 | `brnc_active_flg` | `integer` | YES | nan |
| 7 | `brnc_pqi_relevant_flg` | `integer` | YES | nan |
| 8 | `brnc_opening_date` | `timestamp without time zone` | YES | nan |
| 9 | `brnc_opening_dtid` | `bigint` | YES | nan |
| 10 | `brnc_closing_date` | `timestamp without time zone` | YES | nan |
| 11 | `brnc_closing_dtid` | `bigint` | YES | nan |
| 12 | `brnc_changing_date` | `timestamp without time zone` | YES | nan |
| 13 | `brnc_changing_dtid` | `bigint` | YES | nan |
| 14 | `brnc_operator` | `character varying(9)` | YES | 9 |
| 15 | `brnc_network_code` | `character varying(30)` | YES | 30 |
| 16 | `brnc_network` | `character varying(180)` | YES | 180 |
| 17 | `brnc_iata` | `character varying(9)` | YES | 9 |
| 18 | `brnc_amadeus` | `character varying(18)` | YES | 18 |
| 19 | `brnc_toma` | `character varying(15)` | YES | 15 |
| 20 | `brnc_agency_id` | `numeric(10,0)` | YES | 10 |
| 21 | `brnc_agency_name` | `character varying(90)` | YES | 90 |
| 22 | `brnc_licensee_code` | `numeric(10,0)` | YES | 10 |
| 23 | `brnc_licensee_account` | `character varying(90)` | YES | 90 |
| 24 | `brnc_bookable_flg` | `integer` | YES | nan |
| 25 | `brnc_bookable_intern_flg` | `integer` | YES | nan |
| 26 | `brnc_bookable_online_flg` | `integer` | YES | nan |
| 27 | `brnc_bookable_gds_flg` | `integer` | YES | nan |
| 28 | `brnc_virtual_flg` | `integer` | YES | nan |
| 29 | `brnc_meet_and_greet_flg` | `integer` | YES | nan |
| 30 | `brnc_data_requirement_flg` | `integer` | YES | nan |
| 31 | `brnc_shuttle_type` | `character varying(4)` | YES | 4 |
| 32 | `brnc_24h_open_flg` | `integer` | YES | nan |
| 33 | `brnc_leasing_flg` | `integer` | YES | nan |
| 34 | `brnc_off_airport_flg` | `integer` | YES | nan |
| 35 | `brnc_location_commission_flg` | `integer` | YES | nan |
| 36 | `brnc_vat_open_flg` | `integer` | YES | nan |
| 37 | `brnc_third_party_supplier_flg` | `integer` | YES | nan |
| 38 | `brnc_service_charge_flg` | `integer` | YES | nan |
| 39 | `brnc_ooh_pickup` | `character varying(10)` | YES | 10 |
| 40 | `brnc_ooh_return` | `character varying(10)` | YES | 10 |
| 41 | `brnc_gat_delivery_flg` | `integer` | YES | nan |
| 42 | `brnc_main_type` | `character varying(13)` | YES | 13 |
| 43 | `brnc_parent` | `integer` | YES | nan |
| 44 | `brnc_type_code` | `character varying(6)` | YES | 6 |
| 45 | `brnc_type` | `character varying(180)` | YES | 180 |
| 46 | `brnc_sa_type_code` | `character varying(3)` | YES | 3 |
| 47 | `brnc_sa_type` | `character varying(180)` | YES | 180 |
| 48 | `brnc_delivery_code` | `character varying(3)` | YES | 3 |
| 49 | `brnc_delivery` | `character varying(180)` | YES | 180 |
| 50 | `brnc_collection_code` | `character varying(3)` | YES | 3 |
| 51 | `brnc_collection` | `character varying(180)` | YES | 180 |
| 52 | `brnc_delivery_range` | `integer` | YES | nan |
| 53 | `brnc_fleet_code` | `character varying(124)` | YES | 124 |
| 54 | `brnc_pool_code` | `integer` | YES | nan |
| 55 | `brnc_pool_name` | `character varying(90)` | YES | 90 |
| 56 | `brnc_pool_type_code` | `smallint` | YES | nan |
| 57 | `brnc_pool_type_desc` | `character varying(180)` | YES | 180 |
| 58 | `brnc_continent` | `character varying(180)` | YES | 180 |
| 59 | `brnc_country_code` | `character varying(9)` | YES | 9 |
| 60 | `brnc_country_code_iso` | `character varying(90)` | YES | 90 |
| 61 | `brnc_country` | `character varying(90)` | YES | 90 |
| 62 | `brnc_region_code` | `integer` | YES | nan |
| 63 | `brnc_region` | `character varying(180)` | YES | 180 |
| 64 | `brnc_rate_region_code` | `character varying(9)` | YES | 9 |
| 65 | `brnc_state_code` | `character varying(6)` | YES | 6 |
| 66 | `brnc_state` | `character varying(180)` | YES | 180 |
| 67 | `brnc_postal_code` | `character varying(30)` | YES | 30 |
| 68 | `brnc_city` | `character varying(90)` | YES | 90 |
| 69 | `brnc_street` | `character varying(90)` | YES | 90 |
| 70 | `brnc_latitude` | `numeric(9,6)` | YES | 9 |
| 71 | `brnc_longitude` | `numeric(9,6)` | YES | 9 |
| 72 | `brnc_house` | `character varying(90)` | YES | 90 |
| 73 | `brnc_fax` | `character varying(90)` | YES | 90 |
| 74 | `brnc_email` | `character varying(765)` | YES | 765 |
| 75 | `brnc_phone_external` | `character varying(90)` | YES | 90 |
| 76 | `brnc_phone_emergency` | `character varying(90)` | YES | 90 |
| 77 | `brnc_phone_adac` | `character varying(90)` | YES | 90 |
| 78 | `brnc_phone_internal` | `character varying(90)` | YES | 90 |
| 79 | `brnc_manager` | `character varying(181)` | YES | 181 |
| 80 | `brnc_manager_first_name` | `character varying(90)` | YES | 90 |
| 81 | `brnc_manager_last_name` | `character varying(90)` | YES | 90 |
| 82 | `brnc_manager_email` | `character varying(765)` | YES | 765 |
| 83 | `brnc_manager_phone` | `character varying(90)` | YES | 90 |
| 84 | `brnc_agency_manager` | `character varying(181)` | YES | 181 |
| 85 | `brnc_agency_email` | `character varying(765)` | YES | 765 |
| 86 | `brnc_repair_center` | `integer` | YES | nan |
| 87 | `brnc_repair_center_email` | `character varying(765)` | YES | 765 |
| 88 | `brnc_time_zone` | `character varying(150)` | YES | 150 |
| 89 | `brnc_time_offset` | `smallint` | YES | nan |
| 90 | `brnc_advance_booking_time` | `smallint` | YES | nan |
| 91 | `brnc_open_time` | `character varying(2296)` | YES | 2296 |
| 92 | `brnc_cashbox_limit` | `integer` | YES | nan |
| 93 | `brnc_cashbox_flg` | `integer` | YES | nan |
| 94 | `brnc_cashbox_type` | `character varying(3)` | YES | 3 |
| 95 | `brnc_depot_flg` | `integer` | YES | nan |
| 96 | `brnc_24h_flg` | `integer` | YES | nan |
| 97 | `brnc_fastlane_flg` | `integer` | YES | nan |
| 98 | `brnc_out_of_hours_flg` | `integer` | YES | nan |
| 99 | `brnc_choiceupgrade_flg` | `integer` | YES | nan |
| 100 | `brnc_max_unlock_distance` | `integer` | YES | nan |
| 101 | `brnc_min_advnc_booking_period` | `smallint` | YES | nan |
| 102 | `brnc_first_upgr_free_flg` | `integer` | YES | nan |
| 103 | `brnc_distance_to_station` | `integer` | YES | nan |
| 104 | `brnc_lat_of_parking_location` | `numeric(9,6)` | YES | 9 |
| 105 | `brnc_long_of_parking_location` | `numeric(9,6)` | YES | 9 |
| 106 | `brnc_fastlane_branch_type` | `character varying(30)` | YES | 30 |
| 107 | `brnc_ra_per_email_flg` | `integer` | YES | nan |
| 108 | `brnc_name2` | `character varying(90)` | YES | 90 |
| 109 | `brnc_return_name` | `character varying(90)` | YES | 90 |
| 110 | `brnc_return_house` | `character varying(90)` | YES | 90 |
| 111 | `brnc_return_street` | `character varying(90)` | YES | 90 |
| 112 | `brnc_return_city` | `character varying(90)` | YES | 90 |
| 113 | `brnc_return_postal_code` | `character varying(30)` | YES | 30 |
| 114 | `brnc_return_country_code` | `character varying(9)` | YES | 9 |
| 115 | `brnc_return_country` | `character varying(90)` | YES | 90 |
| 116 | `brnc_return_address_different_flg` | `integer` | YES | nan |
| 117 | `brnc_available_cobra_checkout_flg` | `integer` | YES | nan |
| 118 | `brnc_pickup_comment` | `character varying(528)` | YES | 528 |
| 119 | `brnc_dropoff_comment` | `character varying(528)` | YES | 528 |
| 120 | `brnc_xpress_enabled_flg` | `integer` | YES | nan |
| 121 | `brnc_xpress_enabled_timestamp` | `timestamp without time zone` | YES | nan |
| 122 | `brnc_xpress_disabled_timestamp` | `timestamp without time zone` | YES | nan |
| 123 | `brnc_emergency_service_flg` | `integer` | YES | nan |
| 124 | `brnc_area_director` | `character varying(181)` | YES | 181 |
| 125 | `brnc_area_director_first_name` | `character varying(90)` | YES | 90 |
| 126 | `brnc_area_director_last_name` | `character varying(90)` | YES | 90 |
| 127 | `brnc_area_director_email` | `character varying(765)` | YES | 765 |
| 128 | `brnc_area_director_phone` | `character varying(90)` | YES | 90 |
| 129 | `pk` | `bigint` | YES | nan |
| 130 | `sys_ins_datm` | `timestamp without time zone` | YES | nan |
| 131 | `sys_upd_datm` | `timestamp without time zone` | YES | nan |

## `common_shop.mn_dim_mandants`

**Filas para mandant 409:** 1

**Columnas timestamp (candidatos watermark):** `sys_ins_datm, sys_upd_datm`

**Posibles PK:** `mndt_code, mndt_iso_code, mndt_country_code`


### Columnas (48)

| # | Columna | Tipo | Nullable | Max len |
|---|---|---|---|---|
| 1 | `mndt_code` | `integer` | YES | nan |
| 2 | `mndt_name` | `character varying(90)` | YES | 90 |
| 3 | `mndt_iso_code` | `character varying(90)` | YES | 90 |
| 4 | `mndt_country_code` | `character varying(9)` | YES | 9 |
| 5 | `mndt_country` | `character varying(180)` | YES | 180 |
| 6 | `mndt_country_eng` | `character varying(180)` | YES | 180 |
| 7 | `mndt_tax_rate` | `numeric(6,3)` | YES | 6 |
| 8 | `mndt_operator` | `character varying(3)` | YES | 3 |
| 9 | `mndt_third_party_flg` | `integer` | YES | nan |
| 10 | `mndt_bank_block` | `smallint` | YES | nan |
| 11 | `mndt_corp_card_num` | `character varying(18)` | YES | 18 |
| 12 | `mndt_cost_center` | `integer` | YES | nan |
| 13 | `mndt_debit_account` | `character varying(9)` | YES | 9 |
| 14 | `mndt_debit_account_from` | `numeric(10,0)` | YES | 10 |
| 15 | `mndt_debit_account_to` | `numeric(10,0)` | YES | 10 |
| 16 | `mndt_long_time_rental_flg` | `integer` | YES | nan |
| 17 | `mndt_long_time_rental_days` | `integer` | YES | nan |
| 18 | `mndt_software` | `character varying(180)` | YES | 180 |
| 19 | `mndt_online_flg` | `integer` | YES | nan |
| 20 | `mndt_prepaid_flg` | `integer` | YES | nan |
| 21 | `mndt_currency_code` | `character varying(12)` | YES | 12 |
| 22 | `mndt_active_flg` | `integer` | YES | nan |
| 23 | `mndt_corporate_flg` | `integer` | YES | nan |
| 24 | `mndt_franchise_flg` | `integer` | YES | nan |
| 25 | `mndt_franchise_reporting_flg` | `integer` | YES | nan |
| 26 | `mndt_drive_now_flg` | `integer` | YES | nan |
| 27 | `mndt_leasing_flg` | `integer` | YES | nan |
| 28 | `mndt_yield_relevant_flg` | `integer` | YES | nan |
| 29 | `mndt_yield_main_fir_flg` | `integer` | YES | nan |
| 30 | `cstc_code_franchise` | `integer` | YES | nan |
| 31 | `glac_code_clearing` | `numeric(10,0)` | YES | 10 |
| 32 | `mndt_header_1` | `character varying(234)` | YES | 234 |
| 33 | `mndt_header_2` | `character varying(234)` | YES | 234 |
| 34 | `mndt_header_3` | `character varying(234)` | YES | 234 |
| 35 | `mndt_header_4` | `character varying(234)` | YES | 234 |
| 36 | `mndt_header_5` | `character varying(234)` | YES | 234 |
| 37 | `mndt_header_6` | `character varying(234)` | YES | 234 |
| 38 | `mndt_vat_id` | `character varying(45)` | YES | 45 |
| 39 | `mndt_vat_details` | `character varying(231)` | YES | 231 |
| 40 | `mndt_footer_1` | `character varying(231)` | YES | 231 |
| 41 | `mndt_footer_2` | `character varying(231)` | YES | 231 |
| 42 | `mndt_footer_3` | `character varying(231)` | YES | 231 |
| 43 | `mndt_footer_4` | `character varying(231)` | YES | 231 |
| 44 | `mndt_footer_5` | `character varying(231)` | YES | 231 |
| 45 | `mndt_footer_6` | `character varying(231)` | YES | 231 |
| 46 | `pk` | `bigint` | YES | nan |
| 47 | `sys_ins_datm` | `timestamp without time zone` | YES | nan |
| 48 | `sys_upd_datm` | `timestamp without time zone` | YES | nan |

## `customer_shop.pa_dim_agencies_franchise`

**Filas para mandant 409:** 651

**Columnas timestamp (candidatos watermark):** `sys_ins_datm, sys_upd_datm`

**Posibles PK:** `mndt_code, agnc_type_code`


### Columnas (12)

| # | Columna | Tipo | Nullable | Max len |
|---|---|---|---|---|
| 1 | `mndt_code` | `integer` | YES | nan |
| 2 | `agnc_age` | `numeric(10,0)` | YES | 10 |
| 3 | `agnc_iata` | `character varying(30)` | YES | 30 |
| 4 | `agnc_type_code` | `smallint` | YES | nan |
| 5 | `agnc_type` | `character varying(180)` | YES | 180 |
| 6 | `agnc_subsidiary_num` | `numeric(10,0)` | YES | 10 |
| 7 | `agnc_subsidiary_name` | `character varying(272)` | YES | 272 |
| 8 | `agnc_parent_num` | `numeric(10,0)` | YES | 10 |
| 9 | `agnc_parent_name` | `character varying(272)` | YES | 272 |
| 10 | `agnc_country` | `character varying(90)` | YES | 90 |
| 11 | `sys_ins_datm` | `timestamp without time zone` | YES | nan |
| 12 | `sys_upd_datm` | `timestamp without time zone` | YES | nan |

## `customer_shop.pa_dim_partners_franchise`

**Filas para mandant 409:** 902

**Columnas timestamp (candidatos watermark):** `prtn_customer_created_date, sys_ins_datm, sys_upd_datm`

**Posibles PK:** `mndt_code, prtn_kdnr, prtn_blocked_status_code`


### Columnas (17)

| # | Columna | Tipo | Nullable | Max len |
|---|---|---|---|---|
| 1 | `mndt_code` | `integer` | YES | nan |
| 2 | `prtn_kdnr` | `numeric(10,0)` | YES | 10 |
| 3 | `mndt_code_prtn` | `integer` | YES | nan |
| 4 | `prtn_customer_created_date` | `timestamp without time zone` | YES | nan |
| 5 | `prtn_blocked_status_code` | `smallint` | YES | nan |
| 6 | `prtn_blocked_status` | `character varying(180)` | YES | 180 |
| 7 | `prtn_registration_range_code` | `character varying(9)` | YES | 9 |
| 8 | `prtn_name` | `character varying(272)` | YES | 272 |
| 9 | `prtn_subsidiary_num` | `numeric(10,0)` | YES | 10 |
| 10 | `prtn_subsidiary_name` | `character varying(272)` | YES | 272 |
| 11 | `prtn_parent_num` | `numeric(10,0)` | YES | 10 |
| 12 | `prtn_parent_name` | `character varying(272)` | YES | 272 |
| 13 | `prtn_country_code` | `character varying(9)` | YES | 9 |
| 14 | `prtn_invoice_collection_code` | `smallint` | YES | nan |
| 15 | `prtn_invoice_collection_desc` | `character varying(180)` | YES | 180 |
| 16 | `sys_ins_datm` | `timestamp without time zone` | YES | nan |
| 17 | `sys_upd_datm` | `timestamp without time zone` | YES | nan |

## `damage_shop.dm_dim_damage_cases_franchise`

**Filas para mandant 409:** 0

**Columnas timestamp (candidatos watermark):** `sys_ins_datm, sys_upd_datm`

**Posibles PK:** `mndt_code, damg_snr, damg_damage_case_id`


### Columnas (5)

| # | Columna | Tipo | Nullable | Max len |
|---|---|---|---|---|
| 1 | `mndt_code` | `integer` | YES | nan |
| 2 | `damg_snr` | `bigint` | YES | nan |
| 3 | `damg_damage_case_id` | `character varying(288)` | YES | 288 |
| 4 | `sys_ins_datm` | `timestamp without time zone` | YES | nan |
| 5 | `sys_upd_datm` | `timestamp without time zone` | YES | nan |

## `damage_shop.dm_fct_damage_details_franchise`

**Filas para mandant 409:** 0

**Columnas timestamp (candidatos watermark):** `ddet_source_changed_datm, ddet_source_timestamp_datm, ddet_last_timestamp, sys_ins_datm, sys_upd_datm`

**Posibles PK:** `mndt_code, damg_snr, ddet_object_code`


### Columnas (27)

| # | Columna | Tipo | Nullable | Max len |
|---|---|---|---|---|
| 1 | `mndt_code` | `integer` | YES | nan |
| 2 | `ddet_dmn` | `numeric(11,0)` | YES | 11 |
| 3 | `damg_snr` | `numeric(10,0)` | YES | 10 |
| 4 | `oprt_bed` | `numeric(10,0)` | YES | 10 |
| 5 | `oprt_bed2` | `numeric(10,0)` | YES | 10 |
| 6 | `ddet_ubtl` | `smallint` | YES | nan |
| 7 | `ddet_object_code` | `integer` | YES | nan |
| 8 | `ddet_object_desc` | `character varying(240)` | YES | 240 |
| 9 | `ddet_position_code` | `smallint` | YES | nan |
| 10 | `ddet_position_desc` | `character varying(240)` | YES | 240 |
| 11 | `ddet_type_code` | `smallint` | YES | nan |
| 12 | `ddet_type_desc` | `character varying(240)` | YES | 240 |
| 13 | `ddet_severity_code` | `smallint` | YES | nan |
| 14 | `ddet_severity_desc` | `character varying(240)` | YES | 240 |
| 15 | `ddet_position` | `integer` | YES | nan |
| 16 | `ddet_damage_group` | `smallint` | YES | nan |
| 17 | `ddet_damage_group_desc` | `character varying(240)` | YES | 240 |
| 18 | `vdrd_repair_status_code` | `character varying(3)` | YES | 3 |
| 19 | `vdrd_repair_status` | `character varying(180)` | YES | 180 |
| 20 | `ddet_print_status_flg` | `integer` | YES | nan |
| 21 | `ddet_source_changed_datm` | `timestamp without time zone` | YES | nan |
| 22 | `ddet_source_timestamp_datm` | `timestamp without time zone` | YES | nan |
| 23 | `ddet_source_deleted_flg` | `integer` | YES | nan |
| 24 | `ddet_last_timestamp` | `timestamp without time zone` | YES | nan |
| 25 | `pk` | `bigint` | YES | nan |
| 26 | `sys_ins_datm` | `timestamp without time zone` | YES | nan |
| 27 | `sys_upd_datm` | `timestamp without time zone` | YES | nan |

## `damage_shop.dm_fct_damages`

**Filas para mandant 409:** 0

**Columnas timestamp (candidatos watermark):** `damg_date, damg_datm, damg_log_date, damg_log_datm, damg_last_changed_date, damg_claim_date, damg_last_remark_changed_date, damg_exclusion_date, damg_customer_mst_date, damg_customer_ter_date, damg_mk2_date, damg_last_timestamp, sys_ins_datm, sys_upd_datm`

**Posibles PK:** `damg_snr, mndt_code, brnc_code`


### Columnas (107)

| # | Columna | Tipo | Nullable | Max len |
|---|---|---|---|---|
| 1 | `damg_snr` | `numeric(10,0)` | YES | 10 |
| 2 | `mndt_code` | `integer` | YES | nan |
| 3 | `brnc_code` | `integer` | YES | nan |
| 4 | `vhcl_int_num` | `numeric(10,0)` | YES | 10 |
| 5 | `rntl_mvnr` | `numeric(10,0)` | YES | 10 |
| 6 | `cstm_kdnr` | `numeric(10,0)` | YES | 10 |
| 7 | `oprt_bed` | `numeric(10,0)` | YES | 10 |
| 8 | `oprt_bed_remark` | `numeric(10,0)` | YES | 10 |
| 9 | `jrny_journey_id` | `character varying(108)` | YES | 108 |
| 10 | `prtn_kdnr_liability_insurance` | `numeric(10,0)` | YES | 10 |
| 11 | `damg_scd_flg` | `integer` | YES | nan |
| 12 | `damg_type_code` | `smallint` | YES | nan |
| 13 | `damg_type` | `character varying(180)` | YES | 180 |
| 14 | `damg_type_german` | `character varying(180)` | YES | 180 |
| 15 | `damg_damage_kind` | `smallint` | YES | nan |
| 16 | `damg_date` | `timestamp without time zone` | YES | nan |
| 17 | `damg_datm` | `timestamp without time zone` | YES | nan |
| 18 | `damg_date_dtid` | `integer` | YES | nan |
| 19 | `damg_vhv_num` | `character varying(90)` | YES | 90 |
| 20 | `damg_place` | `character varying(2100)` | YES | 2100 |
| 21 | `damg_causer_code` | `smallint` | YES | nan |
| 22 | `damg_causer` | `character varying(180)` | YES | 180 |
| 23 | `damg_causer_german` | `character varying(180)` | YES | 180 |
| 24 | `damg_closure_vcod_code` | `character varying(9)` | YES | 9 |
| 25 | `damg_closure_vcod` | `character varying(180)` | YES | 180 |
| 26 | `damg_closure_fcat_code` | `character varying(9)` | YES | 9 |
| 27 | `damg_closure_fcat` | `character varying(180)` | YES | 180 |
| 28 | `damg_on_hold_vcod_code` | `character varying(9)` | YES | 9 |
| 29 | `damg_log_date` | `timestamp without time zone` | YES | nan |
| 30 | `damg_log_datm` | `timestamp without time zone` | YES | nan |
| 31 | `damg_log_dtid` | `integer` | YES | nan |
| 32 | `damg_last_changed_date` | `timestamp without time zone` | YES | nan |
| 33 | `damg_last_changed_dtid` | `integer` | YES | nan |
| 34 | `damg_claim_date` | `timestamp without time zone` | YES | nan |
| 35 | `damg_claim_dtid` | `integer` | YES | nan |
| 36 | `damg_customer_forward_code` | `character varying(9)` | YES | 9 |
| 37 | `damg_initialy_reported_code` | `smallint` | YES | nan |
| 38 | `damg_initialy_reported` | `character varying(180)` | YES | 180 |
| 39 | `damg_bekz` | `character varying(3)` | YES | 3 |
| 40 | `damg_local_currency_code` | `character varying(12)` | YES | 12 |
| 41 | `damg_repair_amount` | `numeric(19,5)` | YES | 19 |
| 42 | `damg_nbg_filter` | `character varying(14)` | YES | 14 |
| 43 | `damg_auto_close_flg` | `integer` | YES | nan |
| 44 | `damg_manually_closed_flg` | `integer` | YES | nan |
| 45 | `damg_kls_flg` | `integer` | YES | nan |
| 46 | `damg_no_kls_flg` | `integer` | YES | nan |
| 47 | `damg_claim_closed` | `character varying(9)` | YES | 9 |
| 48 | `damg_assessment_value` | `numeric(13,2)` | YES | 13 |
| 49 | `damg_small_damage_flg` | `integer` | YES | nan |
| 50 | `damg_at_checkin_flg` | `integer` | YES | nan |
| 51 | `damg_damage_tool_usage_flg` | `integer` | YES | nan |
| 52 | `damg_appraisal_flg` | `integer` | YES | nan |
| 53 | `damg_reclamation_flg` | `integer` | YES | nan |
| 54 | `damg_receivable_mng_rostock` | `character varying(90)` | YES | 90 |
| 55 | `damg_registr_plate_num` | `character varying(45)` | YES | 45 |
| 56 | `damg_registr_plate_part_num` | `integer` | YES | nan |
| 57 | `damg_apnr` | `smallint` | YES | nan |
| 58 | `damg_foreign_country_flg` | `integer` | YES | nan |
| 59 | `damg_vhcl_remark` | `character varying(12000)` | YES | 12000 |
| 60 | `damg_last_remark_changed_date` | `timestamp without time zone` | YES | nan |
| 61 | `damg_last_remark_changed_dtid` | `integer` | YES | nan |
| 62 | `damg_responsibility_zone_code` | `character varying(9)` | YES | 9 |
| 63 | `damg_responsibility_zone` | `character varying(180)` | YES | 180 |
| 64 | `damg_logged_at_code` | `smallint` | YES | nan |
| 65 | `damg_logged_at_desc` | `character varying(14)` | YES | 14 |
| 66 | `damg_exclusion_date` | `timestamp without time zone` | YES | nan |
| 67 | `damg_exclusion_dtid` | `integer` | YES | nan |
| 68 | `damg_vhcl_plate_opponent` | `character varying(45)` | YES | 45 |
| 69 | `damg_top150_flg` | `character varying(80)` | YES | 80 |
| 70 | `damg_sxt_apnr_number` | `smallint` | YES | nan |
| 71 | `damg_sxv_apnr_number` | `smallint` | YES | nan |
| 72 | `damg_clousure_vbg_type_level1` | `character varying(4)` | YES | 4 |
| 73 | `damg_clousure_vbg_type_level2` | `character varying(10)` | YES | 10 |
| 74 | `damg_customer_mst_date` | `date` | YES | nan |
| 75 | `damg_customer_mst_dtid` | `integer` | YES | nan |
| 76 | `damg_customer_ter_date` | `date` | YES | nan |
| 77 | `damg_customer_ter_dtid` | `integer` | YES | nan |
| 78 | `damg_customer_mst` | `character varying(30)` | YES | 30 |
| 79 | `damg_mk2_date` | `date` | YES | nan |
| 80 | `damg_mk2_dtid` | `integer` | YES | nan |
| 81 | `damg_sxa_apnr_number` | `smallint` | YES | nan |
| 82 | `damg_sxs_apnr_number` | `smallint` | YES | nan |
| 83 | `damg_closure_vcod_info_field` | `character varying(300)` | YES | 300 |
| 84 | `brnc_name` | `character varying(90)` | YES | 90 |
| 85 | `brnc_region` | `character varying(180)` | YES | 180 |
| 86 | `brnc_main_type` | `character varying(13)` | YES | 13 |
| 87 | `damg_sixt_share_flg` | `integer` | YES | nan |
| 88 | `damg_case_status` | `character varying(408)` | YES | 408 |
| 89 | `damg_rp_signed_flg` | `bigint` | YES | nan |
| 90 | `damg_claim_decision` | `character varying(352)` | YES | 352 |
| 91 | `damg_customer_awareness` | `character varying(320)` | YES | 320 |
| 92 | `damg_origin` | `character varying(112)` | YES | 112 |
| 93 | `damg_customer_answer_cluster` | `character varying(180)` | YES | 180 |
| 94 | `damg_autoclosed_flg` | `integer` | YES | nan |
| 95 | `damg_vbg1_flg` | `integer` | YES | nan |
| 96 | `damg_vbg2_flg` | `integer` | YES | nan |
| 97 | `damg_vbg1_dop_flg` | `integer` | YES | nan |
| 98 | `damg_vbg1_too_small_flg` | `integer` | YES | nan |
| 99 | `damg_vbg1_excess_zero_flg` | `integer` | YES | nan |
| 100 | `damg_vbg1_contract_flg` | `integer` | YES | nan |
| 101 | `damg_vbg1_photogate_flg` | `integer` | YES | nan |
| 102 | `damg_last_timestamp` | `timestamp without time zone` | YES | nan |
| 103 | `damg_auto_webform_sent_flg` | `integer` | YES | nan |
| 104 | `damg_auto_webform_received_flg` | `integer` | YES | nan |
| 105 | `pk` | `bigint` | YES | nan |
| 106 | `sys_ins_datm` | `timestamp without time zone` | YES | nan |
| 107 | `sys_upd_datm` | `timestamp without time zone` | YES | nan |

## `fleet_shop.ve_dim_vehicle_groups_franchise`

**Filas para mandant 409:** 13

**Columnas timestamp (candidatos watermark):** `sys_ins_datm, sys_upd_datm`

**Posibles PK:** `mndt_code, vhgr_type_code`


### Columnas (24)

| # | Columna | Tipo | Nullable | Max len |
|---|---|---|---|---|
| 1 | `mndt_code` | `integer` | YES | nan |
| 2 | `vhgr_crs` | `character varying(12)` | YES | 12 |
| 3 | `vhgr_category_level1` | `character varying(15)` | YES | 15 |
| 4 | `vhgr_category_level2` | `character varying(120)` | YES | 120 |
| 5 | `vhgr_category_level3` | `character varying(90)` | YES | 90 |
| 6 | `vhgr_category_level4` | `character varying(12)` | YES | 12 |
| 7 | `vhgr_sub_category_level1` | `character varying(120)` | YES | 120 |
| 8 | `vhgr_sub_category_level2` | `character varying(120)` | YES | 120 |
| 9 | `vhgr_category_level2_order` | `integer` | YES | nan |
| 10 | `vhgr_type_code` | `character varying(3)` | YES | 3 |
| 11 | `vhgr_category_detail` | `character varying(18)` | YES | 18 |
| 12 | `vhgr_control_classification` | `character varying(6)` | YES | 6 |
| 13 | `vhgr_order` | `integer` | YES | nan |
| 14 | `vhgr_rental_class` | `character varying(6)` | YES | 6 |
| 15 | `vhgr_runtime` | `numeric(10,0)` | YES | 10 |
| 16 | `vhgr_elite_flg` | `integer` | YES | nan |
| 17 | `vhgr_luxury_flg` | `integer` | YES | nan |
| 18 | `vhgr_special_flg` | `integer` | YES | nan |
| 19 | `vhgr_additional_info_level3` | `character varying(30)` | YES | 30 |
| 20 | `vhgr_additional_info_level4` | `character varying(30)` | YES | 30 |
| 21 | `vhgr_cgh_flg` | `integer` | YES | nan |
| 22 | `pk` | `bigint` | YES | nan |
| 23 | `sys_ins_datm` | `timestamp without time zone` | YES | nan |
| 24 | `sys_upd_datm` | `timestamp without time zone` | YES | nan |

## `fleet_shop.ve_dim_vehicle_models`

**Filas para mandant 409:** 72,493

**Columnas timestamp (candidatos watermark):** `vhmd_source_created_date, sys_ins_datm, sys_upd_datm`

**Posibles PK:** `vhmd_ref_man_code, vhmd_bodystyle_code, vhmd_transmission_code`


### Columnas (28)

| # | Columna | Tipo | Nullable | Max len |
|---|---|---|---|---|
| 1 | `vhmd_cdef` | `numeric(10,0)` | YES | 10 |
| 2 | `vhmd_brand_name` | `character varying(90)` | YES | 90 |
| 3 | `vhmd_generic_model` | `character varying(45)` | YES | 45 |
| 4 | `vhmd_deriv_model` | `character varying(60)` | YES | 60 |
| 5 | `vhmd_currently_available_flg` | `integer` | YES | nan |
| 6 | `vhmd_ref_man_code` | `character varying(9)` | YES | 9 |
| 7 | `vhmd_ref_man` | `character varying(180)` | YES | 180 |
| 8 | `vhmd_vehicle_type_num` | `integer` | YES | nan |
| 9 | `vhmd_bodystyle_code` | `character varying(30)` | YES | 30 |
| 10 | `vhmd_bodystyle` | `character varying(180)` | YES | 180 |
| 11 | `vhmd_transmission_code` | `character varying(3)` | YES | 3 |
| 12 | `vhmd_transmission` | `character varying(180)` | YES | 180 |
| 13 | `vhmd_power_ps` | `integer` | YES | nan |
| 14 | `vhmd_power_kw` | `integer` | YES | nan |
| 15 | `vhmd_fuel_code` | `character varying(3)` | YES | 3 |
| 16 | `vhmd_fuel` | `character varying(180)` | YES | 180 |
| 17 | `vhmd_cubic_capacity` | `integer` | YES | nan |
| 18 | `vhmd_powered_wheel_code` | `character varying(3)` | YES | 3 |
| 19 | `vhmd_powered_wheel` | `character varying(180)` | YES | 180 |
| 20 | `vhmd_door_num` | `smallint` | YES | nan |
| 21 | `vhmd_seats_num` | `smallint` | YES | nan |
| 22 | `vhmd_total_weight` | `integer` | YES | nan |
| 23 | `vhmd_payload` | `numeric(5,2)` | YES | 5 |
| 24 | `vhmd_trim_nomenclature` | `numeric(2,1)` | YES | 2 |
| 25 | `vhmd_source_created_date` | `timestamp without time zone` | YES | nan |
| 26 | `pk` | `bigint` | YES | nan |
| 27 | `sys_ins_datm` | `timestamp without time zone` | YES | nan |
| 28 | `sys_upd_datm` | `timestamp without time zone` | YES | nan |

## `fleet_shop.ve_dim_vehicles`

**Filas para mandant 409:** 183

**Columnas timestamp (candidatos watermark):** `vhcl_invoice_date, vhcl_delivery_date, vhcl_reg_date, vhcl_first_reg_date, vhcl_last_reg_date, vhcl_first_infleet_date, vhcl_start_depr_date, vhcl_last_rental_dropoff_date, vhcl_defleet_checkin_date, vhcl_defleet_depot_date, vhcl_disposal_date, vhcl_deregistration_date, vhcl_exact_deregistration_date, vhcl_grounded_date, vhcl_final_sale_date, vhcl_defleet_plan_date, vhcl_infleet_document_date, vhcl_min_abm_date, vhcl_first_ci_date, vhcl_first_rental_date, vhcl_mco_date, sys_ins_datm, sys_upd_datm`

**Posibles PK:** `vhcl_int_num, mndt_code, vhcl_type_code`


### Columnas (143)

| # | Columna | Tipo | Nullable | Max len |
|---|---|---|---|---|
| 1 | `vhcl_int_num` | `numeric(10,0)` | YES | 10 |
| 2 | `vhmd_cdef` | `numeric(10,0)` | YES | 10 |
| 3 | `vhcl_def_num` | `numeric(10,0)` | YES | 10 |
| 4 | `vhgr_crs` | `character varying(12)` | YES | 12 |
| 5 | `mndt_code` | `integer` | YES | nan |
| 6 | `brnc_code_franchisee` | `integer` | YES | nan |
| 7 | `brnc_code_first_checkin` | `integer` | YES | nan |
| 8 | `vhcl_vin` | `character varying(60)` | YES | 60 |
| 9 | `vhcl_plate` | `character varying(45)` | YES | 45 |
| 10 | `vhcl_plate1` | `character varying(15)` | YES | 15 |
| 11 | `vhcl_plate2` | `character varying(15)` | YES | 15 |
| 12 | `vhcl_plate3` | `character varying(15)` | YES | 15 |
| 13 | `vhcl_model` | `character varying(180)` | YES | 180 |
| 14 | `vhcl_group` | `character varying(12)` | YES | 12 |
| 15 | `vhcl_model_year` | `smallint` | YES | nan |
| 16 | `vhcl_type_code` | `character varying(3)` | YES | 3 |
| 17 | `vhcl_type` | `character varying(240)` | YES | 240 |
| 18 | `vhcl_type_id` | `integer` | YES | nan |
| 19 | `vhcl_category_level1` | `character varying(15)` | YES | 15 |
| 20 | `vhcl_category_level2` | `character varying(120)` | YES | 120 |
| 21 | `vhcl_category_level3` | `character varying(90)` | YES | 90 |
| 22 | `vhcl_category_level4` | `character varying(12)` | YES | 12 |
| 23 | `vhcl_term_of_group` | `character varying(18)` | YES | 18 |
| 24 | `vhcl_rank` | `integer` | YES | nan |
| 25 | `vhcl_supplier_num` | `numeric(10,0)` | YES | 10 |
| 26 | `vhcl_supplier_name` | `character varying(90)` | YES | 90 |
| 27 | `vhcl_net_status` | `smallint` | YES | nan |
| 28 | `vhcl_condition_status_code` | `smallint` | YES | nan |
| 29 | `vhcl_condition_status` | `character varying(240)` | YES | 240 |
| 30 | `vhcl_expiry_code` | `numeric(10,0)` | YES | 10 |
| 31 | `vhcl_co2` | `smallint` | YES | nan |
| 32 | `vhcl_color` | `character varying(60)` | YES | 60 |
| 33 | `vhcl_upholstery_color` | `character varying(60)` | YES | 60 |
| 34 | `vhcl_odometer_type` | `character varying(3)` | YES | 3 |
| 35 | `vhcl_luxury_car_flg` | `integer` | YES | nan |
| 36 | `vhcl_available_flg` | `smallint` | YES | nan |
| 37 | `vhcl_navigation_flg` | `smallint` | YES | nan |
| 38 | `vhcl_winter_tyres_flg` | `smallint` | YES | nan |
| 39 | `vhcl_drawbar_flg` | `integer` | YES | nan |
| 40 | `vhcl_mobile_key_fastlane_flg` | `integer` | YES | nan |
| 41 | `vhcl_custom_clearance_flg` | `numeric(10,0)` | YES | 10 |
| 42 | `vhcl_satelite_radio_flg` | `integer` | YES | nan |
| 43 | `vhcl_connected_drive_flg` | `integer` | YES | nan |
| 44 | `vhcl_auxiliary_heating_flg` | `integer` | YES | nan |
| 45 | `vhcl_tracker_flg` | `integer` | YES | nan |
| 46 | `vhcl_navigation_cd` | `character varying(12)` | YES | 12 |
| 47 | `vhcl_snap_in_adap_serial` | `character varying(60)` | YES | 60 |
| 48 | `vhcl_telematic_box_flg` | `integer` | YES | nan |
| 49 | `vhcl_telematic_box_status` | `character varying(13)` | YES | 13 |
| 50 | `vhcl_invoice_date` | `timestamp without time zone` | YES | nan |
| 51 | `vhcl_invoice_dtid` | `integer` | YES | nan |
| 52 | `vhcl_delivery_date` | `timestamp without time zone` | YES | nan |
| 53 | `vhcl_delivery_dtid` | `integer` | YES | nan |
| 54 | `vhcl_reg_date` | `timestamp without time zone` | YES | nan |
| 55 | `vhcl_reg_dtid` | `integer` | YES | nan |
| 56 | `vhcl_first_reg_date` | `timestamp without time zone` | YES | nan |
| 57 | `vhcl_first_reg_dtid` | `integer` | YES | nan |
| 58 | `vhcl_last_reg_date` | `timestamp without time zone` | YES | nan |
| 59 | `vhcl_last_reg_dtid` | `integer` | YES | nan |
| 60 | `vhcl_first_infleet_date` | `timestamp without time zone` | YES | nan |
| 61 | `vhcl_first_infleet_dtid` | `integer` | YES | nan |
| 62 | `vhcl_start_depr_date` | `timestamp without time zone` | YES | nan |
| 63 | `vhcl_start_depr_dtid` | `integer` | YES | nan |
| 64 | `vhcl_last_rental_dropoff_date` | `timestamp without time zone` | YES | nan |
| 65 | `vhcl_last_rental_dropoff_dtid` | `integer` | YES | nan |
| 66 | `vhcl_defleet_checkin_date` | `timestamp without time zone` | YES | nan |
| 67 | `vhcl_defleet_checkin_dtid` | `integer` | YES | nan |
| 68 | `vhcl_defleet_depot_date` | `timestamp without time zone` | YES | nan |
| 69 | `vhcl_defleet_depot_dtid` | `integer` | YES | nan |
| 70 | `vhcl_disposal_date` | `timestamp without time zone` | YES | nan |
| 71 | `vhcl_disposal_dtid` | `integer` | YES | nan |
| 72 | `vhcl_deregistration_date` | `timestamp without time zone` | YES | nan |
| 73 | `vhcl_deregistration_dtid` | `integer` | YES | nan |
| 74 | `vhcl_exact_deregistration_date` | `timestamp without time zone` | YES | nan |
| 75 | `vhcl_exact_deregistration_dtid` | `integer` | YES | nan |
| 76 | `vhcl_grounded_date` | `timestamp without time zone` | YES | nan |
| 77 | `vhcl_grounded_dtid` | `integer` | YES | nan |
| 78 | `vhcl_final_sale_date` | `timestamp without time zone` | YES | nan |
| 79 | `vhcl_final_sale_dtid` | `integer` | YES | nan |
| 80 | `vhcl_holding_days` | `smallint` | YES | nan |
| 81 | `vhcl_max_mileage` | `integer` | YES | nan |
| 82 | `vhcl_defleet_plan_date` | `timestamp without time zone` | YES | nan |
| 83 | `vhcl_defleet_plan_dtid` | `integer` | YES | nan |
| 84 | `vhcl_infleet_document_date` | `timestamp without time zone` | YES | nan |
| 85 | `vhcl_infleet_document_dtid` | `integer` | YES | nan |
| 86 | `vhcl_min_abm_date` | `timestamp without time zone` | YES | nan |
| 87 | `vhcl_min_abm_dtid` | `integer` | YES | nan |
| 88 | `vhcl_bbcn_contract` | `character varying(60)` | YES | 60 |
| 89 | `vhcl_bbcn_type` | `character varying(18)` | YES | 18 |
| 90 | `vhcl_purchase_type_code` | `character varying(3)` | YES | 3 |
| 91 | `vhcl_purchase_type` | `character varying(240)` | YES | 240 |
| 92 | `vhcl_insurance_code` | `character varying(6)` | YES | 6 |
| 93 | `vhcl_insurance` | `character varying(240)` | YES | 240 |
| 94 | `vhcl_insurance_type_code` | `character varying(3)` | YES | 3 |
| 95 | `vhcl_insurance_type` | `character varying(240)` | YES | 240 |
| 96 | `vhcl_corporate_status` | `character varying(3)` | YES | 3 |
| 97 | `vhcl_corporate` | `character varying(240)` | YES | 240 |
| 98 | `vhcl_buyback_condition` | `numeric(10,0)` | YES | 10 |
| 99 | `vhcl_buyback_flg` | `integer` | YES | nan |
| 100 | `vhcl_bank_identification` | `integer` | YES | nan |
| 101 | `vhcl_first_ci_date` | `timestamp without time zone` | YES | nan |
| 102 | `vhcl_first_ci_dtid` | `integer` | YES | nan |
| 103 | `vhcl_first_rental_date` | `timestamp without time zone` | YES | nan |
| 104 | `vhcl_first_rental_dtid` | `integer` | YES | nan |
| 105 | `vhcl_remark_insp` | `character varying(30)` | YES | 30 |
| 106 | `vhcl_remark_manf_insp` | `character varying(30)` | YES | 30 |
| 107 | `vhcl_remark_moto_insp` | `character varying(30)` | YES | 30 |
| 108 | `vhcl_remark_serv_insp` | `character varying(30)` | YES | 30 |
| 109 | `vhcl_remark_taco_insp` | `character varying(30)` | YES | 30 |
| 110 | `vhcl_proc_code_insp` | `character varying(9)` | YES | 9 |
| 111 | `vhcl_proc_code_manf_insp` | `character varying(9)` | YES | 9 |
| 112 | `vhcl_proc_code_moto_insp` | `character varying(9)` | YES | 9 |
| 113 | `vhcl_proc_code_serv_insp` | `character varying(9)` | YES | 9 |
| 114 | `vhcl_proc_code_taco_insp` | `character varying(9)` | YES | 9 |
| 115 | `vhcl_price_list` | `numeric(13,2)` | YES | 13 |
| 116 | `vhcl_purchasing_price` | `numeric(13,2)` | YES | 13 |
| 117 | `vhcl_sale_gross_price` | `numeric(13,2)` | YES | 13 |
| 118 | `vhcl_selling_proceeds` | `numeric(13,2)` | YES | 13 |
| 119 | `vhcl_unique_cost` | `numeric(13,2)` | YES | 13 |
| 120 | `vhcl_currency_code` | `character varying(12)` | YES | 12 |
| 121 | `vhcl_mco_date` | `timestamp without time zone` | YES | nan |
| 122 | `vhcl_mco_dtid` | `integer` | YES | nan |
| 123 | `vhcl_mco_location` | `character varying(60)` | YES | 60 |
| 124 | `vhcl_owner_status_code` | `character varying(6)` | YES | 6 |
| 125 | `vhcl_owner_status` | `character varying(240)` | YES | 240 |
| 126 | `vhcl_car_docs` | `character varying(60)` | YES | 60 |
| 127 | `vhcl_fuel_type_short` | `character varying(60)` | YES | 60 |
| 128 | `vhcl_fuel_tank_size` | `integer` | YES | nan |
| 129 | `vhcl_co2_nedc` | `smallint` | YES | nan |
| 130 | `vhcl_radio_code` | `character varying(96)` | YES | 96 |
| 131 | `vhcl_alarm` | `character varying(30)` | YES | 30 |
| 132 | `vhcl_electric_range` | `character varying(60)` | YES | 60 |
| 133 | `vhcl_vcod` | `character varying(9)` | YES | 9 |
| 134 | `vhat_elty` | `character varying(3)` | YES | 3 |
| 135 | `vhat_elty_level2` | `character varying(3)` | YES | 3 |
| 136 | `vhcl_connected_car_data_source` | `character varying(200)` | YES | 200 |
| 137 | `vhcl_connected_car_data_packages` | `character varying(80)` | YES | 80 |
| 138 | `vhcl_connected_car_marketing_package` | `character varying(200)` | YES | 200 |
| 139 | `vhcl_pci_calc_flg_current` | `integer` | YES | nan |
| 140 | `vhcl_za_fleet_status` | `character varying(18)` | YES | 18 |
| 141 | `pk` | `bigint` | YES | nan |
| 142 | `sys_ins_datm` | `timestamp without time zone` | YES | nan |
| 143 | `sys_upd_datm` | `timestamp without time zone` | YES | nan |

## `fleet_shop.ve_fct_vehicles_current`

**Filas para mandant 409:** 106

**Columnas timestamp (candidatos watermark):** `vhcl_start_depr_date, vhcl_pickup_date, vhcl_return_date, vhcl_change_insp_date, vhcl_change_manf_insp_date, vhcl_change_moto_insp_date, vhcl_change_serv_insp_date, vhcl_change_taco_insp_date, vhcl_road_fund_license_date, vhcl_source_changed_date, vhcl_first_rental_date, vhcl_max_mileage_changed_at, vhcl_holding_days_changed_at, sys_ins_datm, sys_upd_datm`

**Posibles PK:** `brnc_code, mndt_code, vhcl_int_num`


### Columnas (71)

| # | Columna | Tipo | Nullable | Max len |
|---|---|---|---|---|
| 1 | `brnc_code` | `integer` | YES | nan |
| 2 | `mndt_code` | `integer` | YES | nan |
| 3 | `brnc_code_return` | `integer` | YES | nan |
| 4 | `brnc_code_handover_rarent` | `integer` | YES | nan |
| 5 | `brnc_code_handover_rahist` | `integer` | YES | nan |
| 6 | `vhcl_int_num` | `numeric(10,0)` | YES | 10 |
| 7 | `vhcl_central_status_code` | `integer` | YES | nan |
| 8 | `vhcl_central_status` | `character varying(240)` | YES | 240 |
| 9 | `vhcl_status_code` | `smallint` | YES | nan |
| 10 | `vhcl_status` | `character varying(240)` | YES | 240 |
| 11 | `vhcl_user_status_code` | `character varying(18)` | YES | 18 |
| 12 | `vhcl_user_status` | `character varying(240)` | YES | 240 |
| 13 | `vhcl_owner_status_code` | `character varying(6)` | YES | 6 |
| 14 | `vhcl_owner_status` | `character varying(240)` | YES | 240 |
| 15 | `vhcl_group` | `character varying(12)` | YES | 12 |
| 16 | `vhcl_supplier_num` | `numeric(10,0)` | YES | 10 |
| 17 | `vhcl_start_depr_date` | `timestamp without time zone` | YES | nan |
| 18 | `vhcl_holding_days` | `smallint` | YES | nan |
| 19 | `vhcl_current_mileage` | `integer` | YES | nan |
| 20 | `vhcl_current_mileage_km` | `integer` | YES | nan |
| 21 | `vhcl_current_run_days` | `bigint` | YES | nan |
| 22 | `vhcl_current_tank_level` | `integer` | YES | nan |
| 23 | `vhcl_current_battery_percentage_level` | `integer` | YES | nan |
| 24 | `vhcl_max_mileage` | `integer` | YES | nan |
| 25 | `vhcl_remaining_days` | `bigint` | YES | nan |
| 26 | `vhcl_rental_agreement` | `numeric(10,0)` | YES | 10 |
| 27 | `vhcl_pickup_date` | `timestamp without time zone` | YES | nan |
| 28 | `vhcl_return_date` | `timestamp without time zone` | YES | nan |
| 29 | `vhcl_rental_days` | `integer` | YES | nan |
| 30 | `vhcl_rental_long_flg` | `integer` | YES | nan |
| 31 | `vhcl_rate` | `character varying(36)` | YES | 36 |
| 32 | `vhcl_parking_slot` | `character varying(60)` | YES | 60 |
| 33 | `vhcl_franchise_flg` | `integer` | YES | nan |
| 34 | `vhcl_on_rent_flg` | `integer` | YES | nan |
| 35 | `vhcl_never_rented_flg` | `integer` | YES | nan |
| 36 | `vhcl_lent_flg` | `integer` | YES | nan |
| 37 | `vhcl_ready_to_rent_flg` | `smallint` | YES | nan |
| 38 | `vhat_long_term_only_flg` | `integer` | YES | nan |
| 39 | `vhcl_cost_center_flg` | `integer` | YES | nan |
| 40 | `vhcl_change_insp_date` | `timestamp without time zone` | YES | nan |
| 41 | `vhcl_change_manf_insp_date` | `timestamp without time zone` | YES | nan |
| 42 | `vhcl_change_moto_insp_date` | `timestamp without time zone` | YES | nan |
| 43 | `vhcl_change_serv_insp_date` | `timestamp without time zone` | YES | nan |
| 44 | `vhcl_change_taco_insp_date` | `timestamp without time zone` | YES | nan |
| 45 | `vhcl_road_fund_license_date` | `timestamp without time zone` | YES | nan |
| 46 | `vhcl_order_num` | `numeric(10,0)` | YES | 10 |
| 47 | `vhcl_order_external_num` | `character varying(192)` | YES | 192 |
| 48 | `vhcl_days_since_first_reg` | `bigint` | YES | nan |
| 49 | `vhcl_overdue_days_flg` | `integer` | YES | nan |
| 50 | `vhcl_overdue_mileage_flg` | `integer` | YES | nan |
| 51 | `vhcl_source_changed_date` | `timestamp without time zone` | YES | nan |
| 52 | `vhcl_remark` | `character varying(4912)` | YES | 4912 |
| 53 | `vhcl_pci_flg` | `integer` | YES | nan |
| 54 | `rntl_status_code` | `smallint` | YES | nan |
| 55 | `rntl_status` | `character varying(180)` | YES | 180 |
| 56 | `vhcl_ra_int_num` | `numeric(10,0)` | YES | 10 |
| 57 | `vhcl_code_cost_center_current` | `integer` | YES | nan |
| 58 | `vhcl_first_rental_date` | `timestamp without time zone` | YES | nan |
| 59 | `vhcl_relevant_rental_agreement_flg` | `integer` | YES | nan |
| 60 | `vhcl_max_mileage_changed_at` | `timestamp without time zone` | YES | nan |
| 61 | `vhcl_holding_days_changed_at` | `timestamp without time zone` | YES | nan |
| 62 | `brnc_code_cost_center` | `bigint` | YES | nan |
| 63 | `vhcl_days_since_status_change` | `bigint` | YES | nan |
| 64 | `vhcl_days_since_last_rel_rent` | `bigint` | YES | nan |
| 65 | `vhcl_days_since_last_rent` | `bigint` | YES | nan |
| 66 | `vhcl_fct_defleeted_grain_time` | `character varying(104)` | YES | 104 |
| 67 | `vhcl_fct_last_rent_grain_time` | `character varying(104)` | YES | 104 |
| 68 | `vhcl_fct_last_rent2_grain_time` | `character varying(104)` | YES | 104 |
| 69 | `pk` | `bigint` | YES | nan |
| 70 | `sys_ins_datm` | `timestamp without time zone` | YES | nan |
| 71 | `sys_upd_datm` | `timestamp without time zone` | YES | nan |

## `fleet_shop.ve_fct_vehicles_current_incl_history`

**Filas para mandant 409:** 183

**Columnas timestamp (candidatos watermark):** `vhcl_start_depr_date, vhcl_pickup_date, vhcl_return_date, vhcl_change_insp_date, vhcl_change_manf_insp_date, vhcl_change_moto_insp_date, vhcl_change_serv_insp_date, vhcl_change_taco_insp_date, vhcl_road_fund_license_date, vhcl_source_changed_date, vhcl_first_rental_date, sys_ins_datm, sys_upd_datm`

**Posibles PK:** `brnc_code, mndt_code, vhcl_int_num`


### Columnas (62)

| # | Columna | Tipo | Nullable | Max len |
|---|---|---|---|---|
| 1 | `brnc_code` | `integer` | YES | nan |
| 2 | `mndt_code` | `integer` | YES | nan |
| 3 | `brnc_code_return` | `integer` | YES | nan |
| 4 | `brnc_code_handover_rarent` | `integer` | YES | nan |
| 5 | `brnc_code_handover_rahist` | `integer` | YES | nan |
| 6 | `vhcl_int_num` | `numeric(10,0)` | YES | 10 |
| 7 | `vhcl_central_status_code` | `integer` | YES | nan |
| 8 | `vhcl_central_status` | `character varying(240)` | YES | 240 |
| 9 | `vhcl_status_code` | `smallint` | YES | nan |
| 10 | `vhcl_status` | `character varying(240)` | YES | 240 |
| 11 | `vhcl_user_status_code` | `character varying(18)` | YES | 18 |
| 12 | `vhcl_user_status` | `character varying(240)` | YES | 240 |
| 13 | `vhcl_owner_status_code` | `character varying(6)` | YES | 6 |
| 14 | `vhcl_owner_status` | `character varying(240)` | YES | 240 |
| 15 | `vhcl_group` | `character varying(12)` | YES | 12 |
| 16 | `vhcl_supplier_num` | `numeric(10,0)` | YES | 10 |
| 17 | `vhcl_start_depr_date` | `timestamp without time zone` | YES | nan |
| 18 | `vhcl_holding_days` | `smallint` | YES | nan |
| 19 | `vhcl_current_mileage` | `integer` | YES | nan |
| 20 | `vhcl_current_mileage_km` | `integer` | YES | nan |
| 21 | `vhcl_current_run_days` | `bigint` | YES | nan |
| 22 | `vhcl_current_tank_level` | `integer` | YES | nan |
| 23 | `vhcl_current_battery_percentage_level` | `integer` | YES | nan |
| 24 | `vhcl_max_mileage` | `integer` | YES | nan |
| 25 | `vhcl_remaining_days` | `bigint` | YES | nan |
| 26 | `vhcl_rental_agreement` | `numeric(10,0)` | YES | 10 |
| 27 | `vhcl_pickup_date` | `timestamp without time zone` | YES | nan |
| 28 | `vhcl_return_date` | `timestamp without time zone` | YES | nan |
| 29 | `vhcl_rental_days` | `integer` | YES | nan |
| 30 | `vhcl_rental_long_flg` | `integer` | YES | nan |
| 31 | `vhcl_rate` | `character varying(36)` | YES | 36 |
| 32 | `vhcl_parking_slot` | `character varying(60)` | YES | 60 |
| 33 | `vhcl_franchise_flg` | `integer` | YES | nan |
| 34 | `vhcl_on_rent_flg` | `integer` | YES | nan |
| 35 | `vhcl_never_rented_flg` | `integer` | YES | nan |
| 36 | `vhcl_lent_flg` | `integer` | YES | nan |
| 37 | `vhcl_ready_to_rent_flg` | `smallint` | YES | nan |
| 38 | `vhat_long_term_only_flg` | `integer` | YES | nan |
| 39 | `vhcl_cost_center_flg` | `integer` | YES | nan |
| 40 | `vhcl_change_insp_date` | `timestamp without time zone` | YES | nan |
| 41 | `vhcl_change_manf_insp_date` | `timestamp without time zone` | YES | nan |
| 42 | `vhcl_change_moto_insp_date` | `timestamp without time zone` | YES | nan |
| 43 | `vhcl_change_serv_insp_date` | `timestamp without time zone` | YES | nan |
| 44 | `vhcl_change_taco_insp_date` | `timestamp without time zone` | YES | nan |
| 45 | `vhcl_road_fund_license_date` | `timestamp without time zone` | YES | nan |
| 46 | `vhcl_order_num` | `numeric(10,0)` | YES | 10 |
| 47 | `vhcl_order_external_num` | `character varying(192)` | YES | 192 |
| 48 | `vhcl_days_since_first_reg` | `bigint` | YES | nan |
| 49 | `vhcl_overdue_days_flg` | `integer` | YES | nan |
| 50 | `vhcl_overdue_mileage_flg` | `integer` | YES | nan |
| 51 | `vhcl_source_changed_date` | `timestamp without time zone` | YES | nan |
| 52 | `vhcl_remark` | `character varying(38880)` | YES | 38880 |
| 53 | `vhcl_pci_flg` | `integer` | YES | nan |
| 54 | `rntl_status_code` | `smallint` | YES | nan |
| 55 | `rntl_status` | `character varying(180)` | YES | 180 |
| 56 | `vhcl_ra_int_num` | `numeric(10,0)` | YES | 10 |
| 57 | `vhcl_code_cost_center_current` | `integer` | YES | nan |
| 58 | `vhcl_first_rental_date` | `timestamp without time zone` | YES | nan |
| 59 | `vhcl_relevant_rental_agreement_flg` | `integer` | YES | nan |
| 60 | `pk` | `bigint` | YES | nan |
| 61 | `sys_ins_datm` | `timestamp without time zone` | YES | nan |
| 62 | `sys_upd_datm` | `timestamp without time zone` | YES | nan |

## `rent_shop.ch_fct_ra_charges_franchise`

**Filas para mandant 409:** 41,689

**Columnas timestamp (candidatos watermark):** `sys_ins_datm, sys_upd_datm`

**Posibles PK:** `mndt_code, chra_mvnr, rntl_rental_currency_code`


### Columnas (32)

| # | Columna | Tipo | Nullable | Max len |
|---|---|---|---|---|
| 1 | `mndt_code` | `integer` | YES | nan |
| 2 | `chra_mvnr` | `numeric(10,0)` | YES | 10 |
| 3 | `chra_konr` | `integer` | YES | nan |
| 4 | `chra_inty` | `character varying(3)` | YES | 3 |
| 5 | `chra_mser` | `smallint` | YES | nan |
| 6 | `chra_pos` | `integer` | YES | nan |
| 7 | `chra_chco` | `character varying(6)` | YES | 6 |
| 8 | `chra_anz1` | `integer` | YES | nan |
| 9 | `chra_blo1` | `integer` | YES | nan |
| 10 | `chra_bet1` | `numeric(13,2)` | YES | 13 |
| 11 | `chra_pst1` | `numeric(5,2)` | YES | 5 |
| 12 | `chra_vat` | `character varying(3)` | YES | 3 |
| 13 | `chra_stk1` | `smallint` | YES | nan |
| 14 | `chra_pkgn` | `numeric(11,0)` | YES | 11 |
| 15 | `rntl_rental_currency_code` | `character varying(12)` | YES | 12 |
| 16 | `rntl_local_currency_code` | `character varying(12)` | YES | 12 |
| 17 | `rntl_paid_currency_code` | `character varying(9)` | YES | 9 |
| 18 | `rntl_exchange_rate` | `numeric(13,5)` | YES | 13 |
| 19 | `rntl_exchange_rate_rental` | `numeric(13,5)` | YES | 13 |
| 20 | `rntl_exchange_rate_paid` | `numeric(13,5)` | YES | 13 |
| 21 | `chra_unit_value` | `numeric(31,5)` | YES | 31 |
| 22 | `chra_unit_value_rental` | `numeric(13,2)` | YES | 13 |
| 23 | `chra_unit_value_local` | `numeric(26,5)` | YES | 26 |
| 24 | `chra_unit_value_paid` | `numeric(26,5)` | YES | 26 |
| 25 | `chra_unit_num` | `integer` | YES | nan |
| 26 | `chra_value` | `numeric(38,5)` | YES | 38 |
| 27 | `chra_value_rental` | `numeric(25,2)` | YES | 25 |
| 28 | `chra_value_local` | `numeric(37,5)` | YES | 37 |
| 29 | `chra_value_paid` | `numeric(37,5)` | YES | 37 |
| 30 | `pk` | `bigint` | YES | nan |
| 31 | `sys_ins_datm` | `timestamp without time zone` | YES | nan |
| 32 | `sys_upd_datm` | `timestamp without time zone` | YES | nan |

## `rent_shop.ch_fct_rs_charges_franchise`

**Filas para mandant 409:** 57,987

**Columnas timestamp (candidatos watermark):** `sys_ins_datm, sys_upd_datm`

**Posibles PK:** `mndt_code, chrs_resn, rsrv_rental_currency_code`


### Columnas (32)

| # | Columna | Tipo | Nullable | Max len |
|---|---|---|---|---|
| 1 | `mndt_code` | `integer` | YES | nan |
| 2 | `chrs_resn` | `numeric(10,0)` | YES | 10 |
| 3 | `chrs_konr` | `integer` | YES | nan |
| 4 | `chrs_inty` | `character varying(3)` | YES | 3 |
| 5 | `chrs_mser` | `smallint` | YES | nan |
| 6 | `chrs_pos` | `integer` | YES | nan |
| 7 | `chrs_chco` | `character varying(6)` | YES | 6 |
| 8 | `chrs_anz1` | `integer` | YES | nan |
| 9 | `chrs_blo1` | `integer` | YES | nan |
| 10 | `chrs_bet1` | `numeric(13,2)` | YES | 13 |
| 11 | `chrs_pst1` | `numeric(5,2)` | YES | 5 |
| 12 | `chrs_vat` | `character varying(3)` | YES | 3 |
| 13 | `chrs_stk1` | `smallint` | YES | nan |
| 14 | `chrs_pkgn` | `numeric(11,0)` | YES | 11 |
| 15 | `rsrv_rental_currency_code` | `character varying(12)` | YES | 12 |
| 16 | `rsrv_local_currency_code` | `character varying(12)` | YES | 12 |
| 17 | `rsrv_paid_currency_code` | `character varying(9)` | YES | 9 |
| 18 | `rsrv_exchange_rate` | `numeric(13,5)` | YES | 13 |
| 19 | `rsrv_exchange_rate_rental` | `numeric(13,5)` | YES | 13 |
| 20 | `rsrv_exchange_rate_paid` | `numeric(13,5)` | YES | 13 |
| 21 | `chrs_unit_value` | `numeric(31,5)` | YES | 31 |
| 22 | `chrs_unit_value_rental` | `numeric(13,2)` | YES | 13 |
| 23 | `chrs_unit_value_local` | `numeric(26,5)` | YES | 26 |
| 24 | `chrs_unit_value_paid` | `numeric(26,5)` | YES | 26 |
| 25 | `chrs_unit_num` | `integer` | YES | nan |
| 26 | `chrs_value` | `numeric(38,5)` | YES | 38 |
| 27 | `chrs_value_rental` | `numeric(25,2)` | YES | 25 |
| 28 | `chrs_value_local` | `numeric(37,5)` | YES | 37 |
| 29 | `chrs_value_paid` | `numeric(37,5)` | YES | 37 |
| 30 | `pk` | `bigint` | YES | nan |
| 31 | `sys_ins_datm` | `timestamp without time zone` | YES | nan |
| 32 | `sys_upd_datm` | `timestamp without time zone` | YES | nan |

## `rent_shop.ra_dim_scd_channels_franchise`

**Filas para mandant 409:** 14,872

**Columnas timestamp (candidatos watermark):** `sys_ins_datm, sys_upd_datm`

**Posibles PK:** `mndt_code, rntl_mvnr`


### Columnas (9)

| # | Columna | Tipo | Nullable | Max len |
|---|---|---|---|---|
| 1 | `mndt_code` | `integer` | YES | nan |
| 2 | `rntl_mvnr` | `bigint` | YES | nan |
| 3 | `rntl_mser` | `integer` | YES | nan |
| 4 | `rntl_konr` | `integer` | YES | nan |
| 5 | `rntl_scd_level0` | `character varying(5)` | YES | 5 |
| 6 | `rntl_scd_level1` | `character varying(20)` | YES | 20 |
| 7 | `rntl_scd_level2` | `character varying(240)` | YES | 240 |
| 8 | `sys_ins_datm` | `timestamp without time zone` | YES | nan |
| 9 | `sys_upd_datm` | `timestamp without time zone` | YES | nan |

## `rent_shop.ra_fct_rental_vehicles_franchise`

**Filas para mandant 409:** 15,218

**Columnas timestamp (candidatos watermark):** `rate_gdat, rvnc_handover_date, rvnc_handover_datm, rvnc_handover_utc_datm, rvnc_return_date, rvnc_return_datm, rvnc_return_utc_datm, rvnc_source_created_date, rvnc_source_changed_date, sys_ins_datm, sys_upd_datm`

**Posibles PK:** `mndt_code, rntl_mvnr, vhcl_int_num`


### Columnas (38)

| # | Columna | Tipo | Nullable | Max len |
|---|---|---|---|---|
| 1 | `mndt_code` | `integer` | YES | nan |
| 2 | `rntl_mvnr` | `numeric(10,0)` | YES | 10 |
| 3 | `vhcl_int_num` | `numeric(10,0)` | YES | 10 |
| 4 | `rvnc_hser` | `smallint` | YES | nan |
| 5 | `mndt_code_handover` | `integer` | YES | nan |
| 6 | `brnc_code_handover` | `integer` | YES | nan |
| 7 | `mndt_code_return` | `integer` | YES | nan |
| 8 | `brnc_code_return` | `integer` | YES | nan |
| 9 | `rate_gdat` | `timestamp without time zone` | YES | nan |
| 10 | `rate_prl` | `character varying(36)` | YES | 36 |
| 11 | `oprt_bed_handover` | `numeric(10,0)` | YES | 10 |
| 12 | `oprt_bed_return` | `numeric(10,0)` | YES | 10 |
| 13 | `vhmd_vehicle_type_num` | `integer` | YES | nan |
| 14 | `rvnc_handover_date` | `timestamp without time zone` | YES | nan |
| 15 | `rvnc_handover_datm` | `timestamp without time zone` | YES | nan |
| 16 | `rvnc_handover_utc_datm` | `timestamp without time zone` | YES | nan |
| 17 | `rvnc_handover_dtid` | `integer` | YES | nan |
| 18 | `rvnc_return_date` | `timestamp without time zone` | YES | nan |
| 19 | `rvnc_return_datm` | `timestamp without time zone` | YES | nan |
| 20 | `rvnc_return_utc_datm` | `timestamp without time zone` | YES | nan |
| 21 | `rvnc_return_dtid` | `integer` | YES | nan |
| 22 | `rvnc_odometer_type` | `character varying(3)` | YES | 3 |
| 23 | `rvnc_handover_mileage` | `integer` | YES | nan |
| 24 | `rvnc_return_mileage` | `integer` | YES | nan |
| 25 | `rvnc_handover_fuel` | `smallint` | YES | nan |
| 26 | `rvnc_return_fuel` | `smallint` | YES | nan |
| 27 | `rvnc_fueled_litres` | `numeric(7,2)` | YES | 7 |
| 28 | `rvnc_handover_charge_level` | `integer` | YES | nan |
| 29 | `rvnc_return_charge_level` | `integer` | YES | nan |
| 30 | `rvnc_source_created_date` | `timestamp without time zone` | YES | nan |
| 31 | `rvnc_source_changed_date` | `timestamp without time zone` | YES | nan |
| 32 | `rvnc_rental_days` | `bigint` | YES | nan |
| 33 | `rvnc_rental_mileage` | `integer` | YES | nan |
| 34 | `rvnc_first_vehicle` | `smallint` | YES | nan |
| 35 | `rvnc_last_vehicle` | `smallint` | YES | nan |
| 36 | `pk` | `bigint` | YES | nan |
| 37 | `sys_ins_datm` | `timestamp without time zone` | YES | nan |
| 38 | `sys_upd_datm` | `timestamp without time zone` | YES | nan |

## `rent_shop.ra_fct_rentals_vwt_franchise`

**Filas para mandant 409:** 14,465

**Columnas timestamp (candidatos watermark):** `rate_gdat, rntl_handover_date, rntl_return_date, rntl_handover_datm, rntl_handover_utc_datm, rntl_return_datm, rntl_return_utc_datm, rntl_accounting_date, rntl_last_changed_date, rntl_correction_date, rntl_waiting_date, rntl_creating_date, rntl_invoiced_date, sys_ins_datm, sys_upd_datm`

**Posibles PK:** `rntl_mvnr, mndt_code, vhcl_int_num`


### Columnas (174)

| # | Columna | Tipo | Nullable | Max len |
|---|---|---|---|---|
| 1 | `rntl_mvnr` | `numeric(10,0)` | YES | 10 |
| 2 | `mndt_code` | `integer` | YES | nan |
| 3 | `brnc_code_handover` | `integer` | YES | nan |
| 4 | `brnc_code_return` | `integer` | YES | nan |
| 5 | `vhcl_int_num` | `numeric(10,0)` | YES | 10 |
| 6 | `vhcl_int_num_current` | `numeric(10,0)` | YES | 10 |
| 7 | `rsrv_resn` | `numeric(10,0)` | YES | 10 |
| 8 | `cstm_kdnr` | `numeric(10,0)` | YES | 10 |
| 9 | `cstm_kdnr_secondary` | `numeric(10,0)` | YES | 10 |
| 10 | `cstm_kdnr_rate` | `numeric(10,0)` | YES | 10 |
| 11 | `vhgr_crs` | `character varying(12)` | YES | 12 |
| 12 | `rate_gdat` | `timestamp without time zone` | YES | nan |
| 13 | `rate_prl` | `character varying(36)` | YES | 36 |
| 14 | `oprt_bed` | `numeric(10,0)` | YES | 10 |
| 15 | `oprt_bed_checkout` | `numeric(10,0)` | YES | 10 |
| 16 | `vtyp_typ` | `integer` | YES | nan |
| 17 | `agnc_age_agency1` | `numeric(10,0)` | YES | 10 |
| 18 | `agnc_age_agency2` | `numeric(10,0)` | YES | 10 |
| 19 | `rmrk_ainr_customer` | `numeric(10,0)` | YES | 10 |
| 20 | `rmrk_ainr_station` | `numeric(10,0)` | YES | 10 |
| 21 | `rntl_mvnr_parent` | `numeric(10,0)` | YES | 10 |
| 22 | `rntl_contract_num` | `numeric(10,0)` | YES | 10 |
| 23 | `rntl_mser` | `smallint` | YES | nan |
| 24 | `rntl_konr` | `integer` | YES | nan |
| 25 | `rntl_type` | `character varying(5)` | YES | 5 |
| 26 | `rntl_type_code` | `character varying(5)` | YES | 5 |
| 27 | `rntl_handover_date` | `timestamp without time zone` | YES | nan |
| 28 | `rntl_handover_dtid` | `integer` | YES | nan |
| 29 | `rntl_return_date` | `timestamp without time zone` | YES | nan |
| 30 | `rntl_return_dtid` | `integer` | YES | nan |
| 31 | `rntl_handover_datm` | `timestamp without time zone` | YES | nan |
| 32 | `rntl_handover_utc_datm` | `timestamp without time zone` | YES | nan |
| 33 | `rntl_return_datm` | `timestamp without time zone` | YES | nan |
| 34 | `rntl_return_utc_datm` | `timestamp without time zone` | YES | nan |
| 35 | `rntl_status_code` | `smallint` | YES | nan |
| 36 | `rntl_status` | `character varying(240)` | YES | 240 |
| 37 | `rntl_accounting_date` | `timestamp without time zone` | YES | nan |
| 38 | `rntl_accounting_dtid` | `integer` | YES | nan |
| 39 | `rntl_accounting_period` | `integer` | YES | nan |
| 40 | `rntl_accountung_status` | `character varying(3)` | YES | 3 |
| 41 | `rntl_last_changed_date` | `timestamp without time zone` | YES | nan |
| 42 | `rntl_last_changed_dtid` | `integer` | YES | nan |
| 43 | `rntl_correction_date` | `timestamp without time zone` | YES | nan |
| 44 | `rntl_correction_dtid` | `integer` | YES | nan |
| 45 | `rntl_order_number` | `character varying(192)` | YES | 192 |
| 46 | `rntl_second_ref_number` | `character varying(192)` | YES | 192 |
| 47 | `rntl_third_ref_number` | `character varying(192)` | YES | 192 |
| 48 | `rntl_terminal_id` | `character varying(60)` | YES | 60 |
| 49 | `rntl_manual_flg` | `integer` | YES | nan |
| 50 | `rntl_linked_rental_flg` | `integer` | YES | nan |
| 51 | `rntl_rapa_yield` | `character varying(80)` | YES | 80 |
| 52 | `rntl_mpln_yield` | `character varying(80)` | YES | 80 |
| 53 | `rntl_plan_num` | `integer` | YES | nan |
| 54 | `rntl_payment_type_code` | `character varying(6)` | YES | 6 |
| 55 | `rntl_payment_type` | `character varying(240)` | YES | 240 |
| 56 | `rntl_payment_type_s_code` | `character varying(6)` | YES | 6 |
| 57 | `rntl_payment_type_s` | `character varying(240)` | YES | 240 |
| 58 | `rntl_billing_type_m_code` | `smallint` | YES | nan |
| 59 | `rntl_billing_type_m` | `character varying(240)` | YES | 240 |
| 60 | `rntl_billing_type_s_code` | `smallint` | YES | nan |
| 61 | `rntl_billing_type_s` | `character varying(240)` | YES | 240 |
| 62 | `rntl_agency1_num` | `numeric(10,0)` | YES | 10 |
| 63 | `rntl_agency1_type_code` | `smallint` | YES | nan |
| 64 | `rntl_agency1_type` | `character varying(240)` | YES | 240 |
| 65 | `rntl_agency2_num` | `numeric(10,0)` | YES | 10 |
| 66 | `rntl_agency2_type_code` | `smallint` | YES | nan |
| 67 | `rntl_agency2_type` | `character varying(240)` | YES | 240 |
| 68 | `rntl_card_status_level1` | `character varying(25)` | YES | 25 |
| 69 | `rntl_card_status_level2` | `character varying(8)` | YES | 8 |
| 70 | `rntl_card_status_level3` | `character varying(6)` | YES | 6 |
| 71 | `rntl_card_status_level3_name` | `character varying(240)` | YES | 240 |
| 72 | `rntl_card2_status_level1` | `character varying(25)` | YES | 25 |
| 73 | `rntl_card2_status_level2` | `character varying(8)` | YES | 8 |
| 74 | `rntl_card2_status_level3` | `character varying(6)` | YES | 6 |
| 75 | `rntl_card2_status_level3_name` | `character varying(240)` | YES | 240 |
| 76 | `rntl_delivery_flg` | `integer` | YES | nan |
| 77 | `rntl_collection_flg` | `integer` | YES | nan |
| 78 | `rntl_fastlane_flg` | `integer` | YES | nan |
| 79 | `rntl_smartstart_flg` | `integer` | YES | nan |
| 80 | `rntl_self_service_flg` | `integer` | YES | nan |
| 81 | `rntl_salesboost_flg` | `integer` | YES | nan |
| 82 | `rntl_cobra_checkout_flg` | `integer` | YES | nan |
| 83 | `rntl_local_currency_code` | `character varying(12)` | YES | 12 |
| 84 | `rntl_rental_currency_code` | `character varying(12)` | YES | 12 |
| 85 | `rntl_paid_m_currency_code` | `character varying(9)` | YES | 9 |
| 86 | `rntl_paid_s_currency_code` | `character varying(9)` | YES | 9 |
| 87 | `rntl_own_insurance_flg` | `integer` | YES | nan |
| 88 | `vhcl_group` | `character varying(12)` | YES | 12 |
| 89 | `vhcl_checked_out_group` | `character varying(12)` | YES | 12 |
| 90 | `vhcl_type_code` | `character varying(3)` | YES | 3 |
| 91 | `cstm_number` | `numeric(10,0)` | YES | 10 |
| 92 | `cstm_name` | `character varying(272)` | YES | 272 |
| 93 | `cstm_company` | `character varying(90)` | YES | 90 |
| 94 | `cstm_parent` | `character varying(90)` | YES | 90 |
| 95 | `cstm_account_manager_num` | `numeric(10,0)` | YES | 10 |
| 96 | `cstm_account_manager_name` | `character varying(90)` | YES | 90 |
| 97 | `rntl_unlimited_flg` | `integer` | YES | nan |
| 98 | `rntl_dynamic_corporate_rate_flg` | `integer` | YES | nan |
| 99 | `rate_type_level1_gare` | `character varying(36)` | YES | 36 |
| 100 | `rate_type_level2_glev` | `character varying(60)` | YES | 60 |
| 101 | `rate_type_level3_aknm` | `character varying(60)` | YES | 60 |
| 102 | `rate_type_level4_aktv` | `character varying(9)` | YES | 9 |
| 103 | `rntl_split_type_code` | `smallint` | YES | nan |
| 104 | `rntl_split_type` | `character varying(180)` | YES | 180 |
| 105 | `rntl_rapid_action_card` | `character varying(60)` | YES | 60 |
| 106 | `rntl_exchange_rate` | `numeric(38,5)` | YES | 38 |
| 107 | `rntl_exchange_rate_rental` | `numeric(38,5)` | YES | 38 |
| 108 | `rntl_exchange_rate_paid_m` | `numeric(38,5)` | YES | 38 |
| 109 | `rntl_exchange_rate_paid_s` | `numeric(38,5)` | YES | 38 |
| 110 | `rntl_tax_percentage_m` | `numeric(5,2)` | YES | 5 |
| 111 | `rntl_tax_percentage_s` | `numeric(5,2)` | YES | 5 |
| 112 | `rntl_revenue` | `numeric(38,2)` | YES | 38 |
| 113 | `rntl_revenue_rental` | `numeric(38,2)` | YES | 38 |
| 114 | `rntl_revenue_local_currency` | `numeric(38,2)` | YES | 38 |
| 115 | `rntl_revenue_main` | `numeric(38,2)` | YES | 38 |
| 116 | `rntl_revenue_main_local` | `numeric(38,2)` | YES | 38 |
| 117 | `rntl_revenue_main_rental` | `numeric(38,2)` | YES | 38 |
| 118 | `rntl_revenue_main_paid` | `numeric(38,2)` | YES | 38 |
| 119 | `rntl_revenue_secondary` | `numeric(38,2)` | YES | 38 |
| 120 | `rntl_revenue_secondary_local` | `numeric(38,2)` | YES | 38 |
| 121 | `rntl_revenue_secondary_rental` | `numeric(38,2)` | YES | 38 |
| 122 | `rntl_revenue_secondary_paid` | `numeric(38,2)` | YES | 38 |
| 123 | `rntl_additional_revenue` | `numeric(38,2)` | YES | 38 |
| 124 | `rntl_additional_revenue_local` | `numeric(38,2)` | YES | 38 |
| 125 | `rntl_corporate_revenue` | `numeric(38,2)` | YES | 38 |
| 126 | `rntl_unlimited_revenue` | `numeric(38,2)` | YES | 38 |
| 127 | `rntl_tax_rental` | `numeric(38,2)` | YES | 38 |
| 128 | `rntl_tax_main_rental` | `numeric(38,2)` | YES | 38 |
| 129 | `rntl_tax_secondary_rental` | `numeric(38,2)` | YES | 38 |
| 130 | `rntl_tax_id_main` | `character varying(192)` | YES | 192 |
| 131 | `rntl_tax_id_secondary` | `character varying(192)` | YES | 192 |
| 132 | `rntl_discount` | `numeric(38,2)` | YES | 38 |
| 133 | `rntl_distount_local` | `numeric(38,2)` | YES | 38 |
| 134 | `rntl_discount_rental` | `numeric(38,2)` | YES | 38 |
| 135 | `rntl_discount_main_rental` | `numeric(38,2)` | YES | 38 |
| 136 | `rntl_discount_secondary_rental` | `numeric(38,2)` | YES | 38 |
| 137 | `rntl_discount_rental1` | `numeric(38,2)` | YES | 38 |
| 138 | `rntl_discount_main_rental1` | `numeric(38,2)` | YES | 38 |
| 139 | `rntl_discount_secondary_rental1` | `numeric(38,2)` | YES | 38 |
| 140 | `rntl_discount_rental2` | `numeric(38,2)` | YES | 38 |
| 141 | `rntl_discount_main_rental2` | `numeric(38,2)` | YES | 38 |
| 142 | `rntl_discount_secondary_rental2` | `numeric(38,2)` | YES | 38 |
| 143 | `rntl_rental_days` | `bigint` | YES | nan |
| 144 | `rntl_rental_seconds` | `bigint` | YES | nan |
| 145 | `rntl_rental_seconds_first_day` | `bigint` | YES | nan |
| 146 | `rntl_rental_seconds_between_days` | `integer` | YES | nan |
| 147 | `rntl_rental_seconds_last_day` | `bigint` | YES | nan |
| 148 | `rntl_yield_cluster_rental_days` | `character varying(11)` | YES | 11 |
| 149 | `rntl_rental_paid_days` | `bigint` | YES | nan |
| 150 | `rntl_delivery_distance` | `integer` | YES | nan |
| 151 | `rntl_collection_distance` | `integer` | YES | nan |
| 152 | `rntl_changed_vehicles_num` | `integer` | YES | nan |
| 153 | `rntl_waiting_flg` | `integer` | YES | nan |
| 154 | `rntl_waiting_date` | `timestamp without time zone` | YES | nan |
| 155 | `rntl_creating_date` | `date` | YES | nan |
| 156 | `rntl_invoiced_date` | `date` | YES | nan |
| 157 | `rntl_voucher_number` | `character varying(60)` | YES | 60 |
| 158 | `rntl_vip_type` | `character varying(9)` | YES | 9 |
| 159 | `rntl_customer_status_type` | `character varying(9)` | YES | 9 |
| 160 | `rntl_dvs_num` | `numeric(10,0)` | YES | 10 |
| 161 | `rntl_excess_fully` | `numeric(11,2)` | YES | 11 |
| 162 | `rntl_excess_partially` | `numeric(11,2)` | YES | 11 |
| 163 | `rntl_external_rental_number` | `character varying(45)` | YES | 45 |
| 164 | `rntl_xpress_flg` | `integer` | YES | nan |
| 165 | `rntl_language_code` | `smallint` | YES | nan |
| 166 | `rntl_subscription_longterm_id` | `character varying(192)` | YES | 192 |
| 167 | `rntl_previous_lt_rental_activity` | `character varying(80)` | YES | 80 |
| 168 | `rntl_mileage_incl` | `integer` | YES | nan |
| 169 | `rntl_mileage_unl` | `character varying(3)` | YES | 3 |
| 170 | `rntl_after_the_fact_flg` | `integer` | YES | nan |
| 171 | `rntl_agc_paid_days` | `integer` | YES | nan |
| 172 | `pk` | `bigint` | YES | nan |
| 173 | `sys_ins_datm` | `timestamp without time zone` | YES | nan |
| 174 | `sys_upd_datm` | `timestamp without time zone` | YES | nan |

## `rent_shop.rs_dim_scd_channels_franchise`

**Filas para mandant 409:** 27,946

**Columnas timestamp (candidatos watermark):** `sys_ins_datm, sys_upd_datm`

**Posibles PK:** `mndt_code, rsrv_resn`


### Columnas (7)

| # | Columna | Tipo | Nullable | Max len |
|---|---|---|---|---|
| 1 | `mndt_code` | `integer` | YES | nan |
| 2 | `rsrv_resn` | `bigint` | YES | nan |
| 3 | `rsrv_scd_level0` | `character varying(5)` | YES | 5 |
| 4 | `rsrv_scd_level1` | `character varying(20)` | YES | 20 |
| 5 | `rsrv_scd_level2` | `character varying(240)` | YES | 240 |
| 6 | `sys_ins_datm` | `timestamp without time zone` | YES | nan |
| 7 | `sys_upd_datm` | `timestamp without time zone` | YES | nan |

## `rent_shop.rs_fct_reservations`

**Filas para mandant 409:** 27,946

**Columnas timestamp (candidatos watermark):** `rate_gdat, rsrv_date, rsrv_datm, rsrv_cet_date, rsrv_cet_datm, rsrv_handover_date, rsrv_handover_datm, rsrv_handover_utc_datm, rsrv_return_date, rsrv_return_datm, rsrv_return_utc_datm, rsrv_last_urs_rq_datm, rsrv_last_urs_rs_datm, rsrv_last_urs_ra_datm, rsrv_last_urs_sa_datm, rsrv_noshow_date, rsrv_noshow_datm, rsrv_cancelled_date, rsrv_cancelled_datm, sys_ins_datm, sys_upd_datm`

**Posibles PK:** `rsrv_resn, mndt_code, rntl_mvnr`


### Columnas (180)

| # | Columna | Tipo | Nullable | Max len |
|---|---|---|---|---|
| 1 | `rsrv_resn` | `numeric(10,0)` | YES | 10 |
| 2 | `mndt_code` | `integer` | YES | nan |
| 3 | `mndt_code_pos` | `integer` | YES | nan |
| 4 | `mndt_code_url` | `integer` | YES | nan |
| 5 | `mndt_code_sea` | `integer` | YES | nan |
| 6 | `brnc_code_handover` | `integer` | YES | nan |
| 7 | `brnc_code_return` | `integer` | YES | nan |
| 8 | `rntl_mvnr` | `numeric(10,0)` | YES | 10 |
| 9 | `cstm_kdnr` | `numeric(10,0)` | YES | 10 |
| 10 | `cstm_kdnr_rate` | `numeric(10,0)` | YES | 10 |
| 11 | `cstm_kdnr_invoiced` | `numeric(10,0)` | YES | 10 |
| 12 | `vhgr_crs` | `character varying(12)` | YES | 12 |
| 13 | `rate_gdat` | `timestamp without time zone` | YES | nan |
| 14 | `rate_prl` | `character varying(36)` | YES | 36 |
| 15 | `rate_code` | `character varying(36)` | YES | 36 |
| 16 | `oprt_bed` | `numeric(10,0)` | YES | 10 |
| 17 | `rsrv_staff_number` | `numeric(10,0)` | YES | 10 |
| 18 | `agnc_age_agency1` | `numeric(10,0)` | YES | 10 |
| 19 | `agnc_age_agency2` | `numeric(10,0)` | YES | 10 |
| 20 | `card_ccnr` | `character varying(60)` | YES | 60 |
| 21 | `card2_ccnr` | `character varying(60)` | YES | 60 |
| 22 | `prsn_peid_m` | `numeric(10,0)` | YES | 10 |
| 23 | `prsn_peid_s` | `numeric(10,0)` | YES | 10 |
| 24 | `rmrk_ainr_customer` | `numeric(10,0)` | YES | 10 |
| 25 | `rmrk_ainr_station` | `numeric(10,0)` | YES | 10 |
| 26 | `rsrv_status_code` | `smallint` | YES | nan |
| 27 | `rsrv_status` | `character varying(9)` | YES | 9 |
| 28 | `rsrv_status_extended` | `character varying(24)` | YES | 24 |
| 29 | `rsrv_date` | `timestamp without time zone` | YES | nan |
| 30 | `rsrv_datm` | `timestamp without time zone` | YES | nan |
| 31 | `rsrv_dtid` | `integer` | YES | nan |
| 32 | `rsrv_cet_date` | `timestamp without time zone` | YES | nan |
| 33 | `rsrv_cet_datm` | `timestamp without time zone` | YES | nan |
| 34 | `rsrv_cet_dtid` | `integer` | YES | nan |
| 35 | `rsrv_reference_number2` | `character varying(192)` | YES | 192 |
| 36 | `rsrv_reference_number1` | `character varying(192)` | YES | 192 |
| 37 | `rsrv_reference_number3` | `character varying(192)` | YES | 192 |
| 38 | `rsrv_security_code` | `character varying(30)` | YES | 30 |
| 39 | `rsrv_payment_type_code` | `character varying(6)` | YES | 6 |
| 40 | `rsrv_payment_type` | `character varying(240)` | YES | 240 |
| 41 | `rsrv_payment_type_s_code` | `character varying(6)` | YES | 6 |
| 42 | `rsrv_payment_type_s` | `character varying(240)` | YES | 240 |
| 43 | `rsrv_billing_type_m_code` | `smallint` | YES | nan |
| 44 | `rsrv_billing_type_m` | `character varying(240)` | YES | 240 |
| 45 | `rsrv_billing_type_s_code` | `smallint` | YES | nan |
| 46 | `rsrv_billing_type_s` | `character varying(240)` | YES | 240 |
| 47 | `rsrv_handover_date` | `timestamp without time zone` | YES | nan |
| 48 | `rsrv_handover_datm` | `timestamp without time zone` | YES | nan |
| 49 | `rsrv_handover_utc_datm` | `timestamp without time zone` | YES | nan |
| 50 | `rsrv_handover_dtid` | `integer` | YES | nan |
| 51 | `rsrv_return_date` | `timestamp without time zone` | YES | nan |
| 52 | `rsrv_return_datm` | `timestamp without time zone` | YES | nan |
| 53 | `rsrv_return_utc_datm` | `timestamp without time zone` | YES | nan |
| 54 | `rsrv_return_dtid` | `integer` | YES | nan |
| 55 | `rsrv_reservation_flg` | `integer` | YES | nan |
| 56 | `rsrv_luxury_flg` | `integer` | YES | nan |
| 57 | `rsrv_barcode_flg` | `integer` | YES | nan |
| 58 | `rsrv_last_urs_rq_datm` | `timestamp without time zone` | YES | nan |
| 59 | `rsrv_last_urs_rq_dtid` | `integer` | YES | nan |
| 60 | `rsrv_last_urs_rs_datm` | `timestamp without time zone` | YES | nan |
| 61 | `rsrv_last_urs_rs_dtid` | `integer` | YES | nan |
| 62 | `rsrv_changes_num` | `bigint` | YES | nan |
| 63 | `rsrv_last_urs_ra_datm` | `timestamp without time zone` | YES | nan |
| 64 | `rsrv_last_urs_ra_dtid` | `integer` | YES | nan |
| 65 | `rsrv_last_urs_sa_datm` | `timestamp without time zone` | YES | nan |
| 66 | `rsrv_last_urs_sa_dtid` | `integer` | YES | nan |
| 67 | `rsrv_cancelled_flg` | `integer` | YES | nan |
| 68 | `rsrv_noshow_flg` | `integer` | YES | nan |
| 69 | `rsrv_noshow_date` | `timestamp without time zone` | YES | nan |
| 70 | `rsrv_noshow_datm` | `timestamp without time zone` | YES | nan |
| 71 | `rsrv_noshow_dtid` | `integer` | YES | nan |
| 72 | `rsrv_prepaid_flg` | `integer` | YES | nan |
| 73 | `rsrv_request_flg` | `integer` | YES | nan |
| 74 | `rsrv_request_level_code` | `smallint` | YES | nan |
| 75 | `rsrv_request_level` | `character varying(180)` | YES | 180 |
| 76 | `rsrv_posl_country_code` | `character varying(9)` | YES | 9 |
| 77 | `rsrv_cancelled_date` | `timestamp without time zone` | YES | nan |
| 78 | `rsrv_cancelled_datm` | `timestamp without time zone` | YES | nan |
| 79 | `rsrv_cancelled_dtid` | `integer` | YES | nan |
| 80 | `rsrv_new_customer_code` | `character varying(3)` | YES | 3 |
| 81 | `rsrv_new_customer` | `character varying(180)` | YES | 180 |
| 82 | `rsrv_source_chl1` | `character varying(90)` | YES | 90 |
| 83 | `rsrv_source_chl2` | `character varying(90)` | YES | 90 |
| 84 | `rsrv_source_chl3` | `character varying(90)` | YES | 90 |
| 85 | `rsrv_tech_source` | `character varying(3)` | YES | 3 |
| 86 | `rsrv_change_chl1` | `character varying(90)` | YES | 90 |
| 87 | `rsrv_change_chl2` | `character varying(90)` | YES | 90 |
| 88 | `rsrv_change_chl3` | `character varying(90)` | YES | 90 |
| 89 | `rsrv_yield_source` | `character varying(60)` | YES | 60 |
| 90 | `rsrv_yield_source_level2` | `character varying(60)` | YES | 60 |
| 91 | `rsrv_yield_source_level3` | `character varying(60)` | YES | 60 |
| 92 | `rsrv_cancelled_source` | `character varying(90)` | YES | 90 |
| 93 | `rsrv_cancelled_partner` | `character varying(90)` | YES | 90 |
| 94 | `rsrv_rapa_yield` | `character varying(80)` | YES | 80 |
| 95 | `rsrv_mpln_yield` | `character varying(80)` | YES | 80 |
| 96 | `rsrv_plan_num` | `integer` | YES | nan |
| 97 | `rsrv_customer_type` | `character varying(180)` | YES | 180 |
| 98 | `rsrv_customer_card_num` | `numeric(10,0)` | YES | 10 |
| 99 | `rsrv_card_status_level1` | `character varying(25)` | YES | 25 |
| 100 | `rsrv_card_status_level2` | `character varying(25)` | YES | 25 |
| 101 | `rsrv_card_status_level3` | `character varying(6)` | YES | 6 |
| 102 | `rsrv_card_status_level3_name` | `character varying(180)` | YES | 180 |
| 103 | `rsrv_customer_card2_num` | `numeric(10,0)` | YES | 10 |
| 104 | `rsrv_card2_status_level1` | `character varying(25)` | YES | 25 |
| 105 | `rsrv_card2_status_level2` | `character varying(25)` | YES | 25 |
| 106 | `rsrv_card2_status_level3` | `character varying(6)` | YES | 6 |
| 107 | `rsrv_card2_status_level3_name` | `character varying(180)` | YES | 180 |
| 108 | `rsrv_delivery_flg` | `integer` | YES | nan |
| 109 | `rsrv_collection_flg` | `integer` | YES | nan |
| 110 | `rsrv_customer_fastlane_flg` | `integer` | YES | nan |
| 111 | `rsrv_type` | `character varying(5)` | YES | 5 |
| 112 | `rsrv_type_code` | `character varying(5)` | YES | 5 |
| 113 | `rsrv_local_currency_code` | `character varying(12)` | YES | 12 |
| 114 | `rsrv_rental_currency_code` | `character varying(12)` | YES | 12 |
| 115 | `rsrv_paid_m_currency_code` | `character varying(9)` | YES | 9 |
| 116 | `rsrv_paid_s_currency_code` | `character varying(9)` | YES | 9 |
| 117 | `rsrv_flight_num` | `character varying(24)` | YES | 24 |
| 118 | `rsrv_secondary_invoice_flg` | `integer` | YES | nan |
| 119 | `cstm_number` | `numeric(10,0)` | YES | 10 |
| 120 | `cstm_name` | `character varying(272)` | YES | 272 |
| 121 | `cstm_company` | `character varying(90)` | YES | 90 |
| 122 | `cstm_parent` | `character varying(90)` | YES | 90 |
| 123 | `rsrv_unlimited_flg` | `integer` | YES | nan |
| 124 | `rate_internal_flg` | `integer` | YES | nan |
| 125 | `rate_subtype` | `character varying(12)` | YES | 12 |
| 126 | `rate_type_level1_gare` | `character varying(36)` | YES | 36 |
| 127 | `rate_type_level2_glev` | `character varying(60)` | YES | 60 |
| 128 | `rate_type_level3_aknm` | `character varying(60)` | YES | 60 |
| 129 | `rate_type_level4_aktv` | `character varying(9)` | YES | 9 |
| 130 | `vhcl_group` | `character varying(12)` | YES | 12 |
| 131 | `vhcl_crs` | `character varying(12)` | YES | 12 |
| 132 | `rsrv_exchange_rate` | `numeric(13,5)` | YES | 13 |
| 133 | `rsrv_exchange_rate_rental` | `numeric(13,5)` | YES | 13 |
| 134 | `rsrv_exchange_rate_paid_m` | `numeric(13,5)` | YES | 13 |
| 135 | `rsrv_exchange_rate_paid_s` | `numeric(13,5)` | YES | 13 |
| 136 | `rsrv_revenue` | `numeric(38,2)` | YES | 38 |
| 137 | `rsrv_revenue_local_currency` | `numeric(38,2)` | YES | 38 |
| 138 | `rsrv_revenue_main` | `numeric(19,2)` | YES | 19 |
| 139 | `rsrv_revenue_main_local` | `numeric(13,2)` | YES | 13 |
| 140 | `rsrv_revenue_secondary` | `numeric(19,2)` | YES | 19 |
| 141 | `rsrv_revenue_secondary_local` | `numeric(13,2)` | YES | 13 |
| 142 | `rsrv_tax_value` | `numeric(38,2)` | YES | 38 |
| 143 | `rsrv_tax_value_local_currency` | `numeric(38,2)` | YES | 38 |
| 144 | `rsrv_tax_value_main` | `numeric(19,2)` | YES | 19 |
| 145 | `rsrv_tax_value_main_local` | `numeric(13,2)` | YES | 13 |
| 146 | `rsrv_tax_value_secondary` | `numeric(19,2)` | YES | 19 |
| 147 | `rsrv_tax_value_secondary_local` | `numeric(13,2)` | YES | 13 |
| 148 | `rsrv_voucher_value` | `numeric(28,11)` | YES | 28 |
| 149 | `rsrv_voucher_value_local` | `numeric(14,2)` | YES | 14 |
| 150 | `rsrv_voucher_value_main` | `numeric(27,11)` | YES | 27 |
| 151 | `rsrv_voucher_value_main_local` | `numeric(13,2)` | YES | 13 |
| 152 | `rsrv_voucher_value_sec` | `numeric(27,11)` | YES | 27 |
| 153 | `rsrv_voucher_value_sec_local` | `numeric(13,2)` | YES | 13 |
| 154 | `rsrv_prepaid_value` | `numeric(28,11)` | YES | 28 |
| 155 | `rsrv_prepaid_value_local` | `numeric(14,2)` | YES | 14 |
| 156 | `rsrv_prepaid_value_main` | `numeric(27,11)` | YES | 27 |
| 157 | `rsrv_prepaid_value_main_local` | `numeric(13,2)` | YES | 13 |
| 158 | `rsrv_prepaid_value_secondary` | `numeric(27,11)` | YES | 27 |
| 159 | `rsrv_prepaid_value_secondary_local` | `numeric(13,2)` | YES | 13 |
| 160 | `rsrv_rental_days` | `integer` | YES | nan |
| 161 | `rsrv_delivery_distance` | `integer` | YES | nan |
| 162 | `rsrv_collection_distance` | `integer` | YES | nan |
| 163 | `rsrv_source_tracking` | `character varying(60)` | YES | 60 |
| 164 | `rsrv_first_source_tracking` | `character varying(60)` | YES | 60 |
| 165 | `rsrv_communication_language_code` | `smallint` | YES | nan |
| 166 | `rsrv_communication_language` | `character varying(180)` | YES | 180 |
| 167 | `rsrv_goodwill_cancellation_flg` | `integer` | YES | nan |
| 168 | `rsrv_goodwill_rsrv_change_flg` | `integer` | YES | nan |
| 169 | `rsrv_internet_vehicle_description` | `character varying(180)` | YES | 180 |
| 170 | `rsrv_gds_vehicle_description` | `character varying(180)` | YES | 180 |
| 171 | `rsrv_guaranteed_group_flg` | `integer` | YES | nan |
| 172 | `rsrv_premium_group_flg` | `integer` | YES | nan |
| 173 | `rsrv_customer_cancellation_flg` | `integer` | YES | nan |
| 174 | `rsrv_zen_reservation_flg` | `integer` | YES | nan |
| 175 | `rsrv_subscription_id` | `character varying(104)` | YES | 104 |
| 176 | `rsrv_agc_paid_days` | `bigint` | YES | nan |
| 177 | `rsrv_rapid_action_card` | `character varying(256)` | YES | 256 |
| 178 | `pk` | `bigint` | YES | nan |
| 179 | `sys_ins_datm` | `timestamp without time zone` | YES | nan |
| 180 | `sys_upd_datm` | `timestamp without time zone` | YES | nan |

## `rent_shop.rt_dim_rates_franchise`

**Filas para mandant 409:** 1,434

**Columnas timestamp (candidatos watermark):** `rate_gdat, rate_vdat, rate_next_gdat, sys_ins_datm, sys_upd_datm`

**Posibles PK:** `mndt_code, rate_provision_type_code, rate_country_code`


### Columnas (39)

| # | Columna | Tipo | Nullable | Max len |
|---|---|---|---|---|
| 1 | `mndt_code` | `integer` | YES | nan |
| 2 | `rate_prl` | `character varying(36)` | YES | 36 |
| 3 | `rate_gdat` | `timestamp without time zone` | YES | nan |
| 4 | `rtbd_bundle` | `character varying(9)` | YES | 9 |
| 5 | `rate_vdat` | `timestamp without time zone` | YES | nan |
| 6 | `rate_next_gdat` | `timestamp without time zone` | YES | nan |
| 7 | `rate_refer_prl` | `character varying(36)` | YES | 36 |
| 8 | `rate_type` | `character varying(29)` | YES | 29 |
| 9 | `rate_provision_type_code` | `character varying(6)` | YES | 6 |
| 10 | `rate_provision_type` | `character varying(180)` | YES | 180 |
| 11 | `rate_subtype` | `character varying(12)` | YES | 12 |
| 12 | `rate_class` | `character varying(9)` | YES | 9 |
| 13 | `rate_business_area_product` | `character varying(192)` | YES | 192 |
| 14 | `rate_bundle` | `character varying(9)` | YES | 9 |
| 15 | `rate_prepaid_flg` | `integer` | YES | nan |
| 16 | `rate_country_code` | `character varying(6)` | YES | 6 |
| 17 | `rate_currency_code` | `character varying(12)` | YES | 12 |
| 18 | `rate_type_level1_gare` | `character varying(36)` | YES | 36 |
| 19 | `rate_type_level2_glev` | `character varying(60)` | YES | 60 |
| 20 | `rate_type_level3_aknm` | `character varying(60)` | YES | 60 |
| 21 | `rate_type_level4_aktv` | `character varying(9)` | YES | 9 |
| 22 | `rate_crm_type_gare_clv` | `character varying(54)` | YES | 54 |
| 23 | `rate_designation` | `character varying(60)` | YES | 60 |
| 24 | `rate_split_type_code` | `smallint` | YES | nan |
| 25 | `rate_split_type` | `character varying(180)` | YES | 180 |
| 26 | `vhcl_type_code` | `character varying(3)` | YES | 3 |
| 27 | `vhcl_yield_type_code` | `character varying(1)` | YES | 1 |
| 28 | `vhcl_type` | `character varying(180)` | YES | 180 |
| 29 | `rate_overlap_flg` | `integer` | YES | nan |
| 30 | `rate_relevant_rental_flg` | `integer` | YES | nan |
| 31 | `rate_internal_flg` | `integer` | YES | nan |
| 32 | `rate_damage_rental_type` | `character varying(8)` | YES | 8 |
| 33 | `rate_incr_rev_relevant_flg` | `integer` | YES | nan |
| 34 | `rate_unlimited_flg` | `integer` | YES | nan |
| 35 | `rate_sixt_flat_flg` | `integer` | YES | nan |
| 36 | `rate_special_wholesaler_split_flg` | `integer` | YES | nan |
| 37 | `pk` | `bigint` | YES | nan |
| 38 | `sys_ins_datm` | `timestamp without time zone` | YES | nan |
| 39 | `sys_upd_datm` | `timestamp without time zone` | YES | nan |