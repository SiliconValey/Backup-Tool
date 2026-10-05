@echo off
REM Genera dist\BackupTool\BackupTool.exe con PyInstaller.
REM --uac-admin hace que Windows pida permisos de administrador al abrirlo
REM (necesarios para exportar drivers y claves Wi-Fi).
REM Se usa "python -m" porque con instalaciones de usuario la carpeta Scripts
REM (donde queda pyinstaller.exe) no suele estar en el PATH.

cd /d "%~dp0"

python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto error

python -m PyInstaller --noconfirm --windowed --uac-admin --name BackupTool ^
    --icon backuptool\resources\icon.ico ^
    --add-data "backuptool\resources;backuptool\resources" ^
    main.py
if errorlevel 1 goto error

echo.
echo Listo: dist\BackupTool\BackupTool.exe
pause
exit /b 0

:error
echo.
echo *** Hubo un error: revisa los mensajes de arriba. ***
pause
exit /b 1
