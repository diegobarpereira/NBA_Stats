@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ========================================
echo    NBA Stats - Iniciando Aplicacao
echo ========================================
echo.

cd /d "%~dp0"

echo [INFO] Verificando Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Python nao encontrado!
    pause
    exit /b 1
)

echo [OK] Python encontrado
echo.

echo [INFO] Iniciando Streamlit (Frontend)...
echo.
echo     Acesse: http://localhost:8501
echo.
echo     Para parar: Ctrl+C
echo.
echo ========================================
echo.

start "NBA Stats - Streamlit" cmd /c "python -m streamlit run app.py"

echo [OK] Aplicacao iniciada!
echo.
pause