@echo off
REM ============================================================
REM  Trust Data Platform - Refresh incremental
REM  Programar en Windows Task Scheduler cada 6 horas.
REM  Bronze incremental + Silver rebuild en una sola corrida.
REM ============================================================

cd /d "%~dp0\.."

echo [%date% %time%] === Refresh start ===

python -m pipelines.bronze.incremental
if errorlevel 1 (
    echo [%date% %time%] FAIL en bronze incremental
    exit /b 1
)

REM TRM oficial USD->COP desde datos.gov.co (Superintendencia / Banrep).
REM Incremental: si llevamos N dias sin correr, recupera las TRM faltantes.
python -m pipelines.bronze.external_trm
if errorlevel 1 (
    echo [%date% %time%] WARN: TRM no actualizada (continuando)
)

python -m pipelines.silver.build
if errorlevel 1 (
    echo [%date% %time%] FAIL en silver build
    exit /b 1
)

echo [%date% %time%] === Refresh OK ===
exit /b 0
