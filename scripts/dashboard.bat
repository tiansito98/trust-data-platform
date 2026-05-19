@echo off
REM ============================================================
REM  Trust Data Platform - Lanzar dashboard Streamlit
REM ============================================================

cd /d "%~dp0\.."

echo === Lanzando Streamlit ===
echo URL: http://localhost:8501
echo Ctrl+C para detener
echo.

streamlit run dashboard\app.py
