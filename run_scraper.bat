@echo off
:: run_scraper.bat
:: Archivo de procesamiento por lotes para la ejecucion diaria automatizada del raspador de REMAJU
title Sistema de Raspado Automatizado Asincrono - REMAJU Poder Judicial

echo ===============================================================================
echo [%date% %time%] INICIANDO RUTINA DIARIA DE EXTRACCION - REMAJU
echo ===============================================================================

echo.
echo [%date% %time%] Paso 1: Activando el entorno virtual de Python (venv)...
if exist ".\venv\Scripts\activate.bat" (
    call .\venv\Scripts\activate.bat
    echo [%date% %time%] Entorno virtual activado exitosamente.
) else (
    echo [ERROR] [%date% %time%] No se encontro el entorno virtual en .\venv\Scripts\activate.bat
    echo Por favor, verifica la ruta del entorno virtual e intenta nuevamente.
    goto :error
)

echo.
echo [%date% %time%] Paso 2: Iniciando el orquestador asincrono principal (main.py)...
if exist ".\main.py" (
    python .\main.py
) else (
    echo [ERROR] [%date% %time%] No se encontro el archivo orquestador en .\main.py
    goto :error
)

echo.
echo ===============================================================================
echo [%date% %time%] PROCESAMIENTO COMPLETADO EXITOSAMENTE
echo ===============================================================================
goto :end

:error
echo.
echo ===============================================================================
echo [ERROR] [%date% %time%] LA EJECUCION DIARIA HA FALLADO. REVISA LOS LOGS.
echo ===============================================================================

:end
echo.
echo Presione cualquier tecla para cerrar esta ventana...
pause > nul
