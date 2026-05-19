@echo off
REM ============================================================
REM  Trust Data Platform - Setup inicial
REM ============================================================

cd /d "%~dp0\.."

echo === Trust Data Platform - Setup ===
echo.
echo [1/3] Instalando dependencias Python...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo.
echo [2/3] Forzando paramiko menor a 4.0 (compatibilidad sshtunnel)...
python -m pip install "paramiko<4.0" --upgrade

echo.
echo [3/3] Verificando instalacion...
python -c "import duckdb, redshift_connector, sshtunnel, paramiko, streamlit; print('OK - todas las dependencias estan instaladas')"
python -c "import paramiko; print('paramiko version:', paramiko.__version__)"

echo.
echo === Setup completo ===
echo.
echo Proximos pasos:
echo   1. copy .env.example .env
echo   2. notepad .env  ^(llenar SIXT_REDSHIFT_PASSWORD^)
echo   3. python -m pipelines.bronze.inspect --test-connection
echo.

pause
