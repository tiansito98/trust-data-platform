-- Contratos con cargo PF en 2026. Fuente: bronze (mirror crudo de Redshift).
-- Una fila por (contrato, codigo). Ano = ano de entrega del vehiculo.
SELECT DISTINCT
       c.chra_mvnr::bigint AS contract_number,
       c.chra_chco         AS charge_code
FROM bronze.rent_shop_ch_fct_ra_charges_franchise c
JOIN bronze.rent_shop_ra_fct_rentals_vwt_franchise r
     ON  r.rntl_mvnr  = c.chra_mvnr
     AND r.mndt_code  = c.mndt_code
WHERE c.mndt_code = 409
  AND c.chra_chco = 'PF'
  AND r.rntl_handover_datm >= DATE '2026-01-01'
  AND r.rntl_handover_datm <  DATE '2027-01-01'
ORDER BY contract_number;
