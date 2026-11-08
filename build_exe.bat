@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo  GCode Tools - Gerador de Executavel (Windows)
echo ============================================================
echo.

echo [1/3] Instalando dependencias do projeto...
python -m pip install -r requirements.txt
if errorlevel 1 goto :erro

echo.
echo [2/3] Instalando PyInstaller...
python -m pip install -r requirements-build.txt
if errorlevel 1 goto :erro

echo.
echo [3/3] Gerando o executavel (isso pode levar alguns minutos)...
python -m PyInstaller --noconfirm --clean GCodeTools.spec
if errorlevel 1 goto :erro

echo.
echo ============================================================
echo  Concluido!
echo  Executavel: dist\GCodeTools\GCodeTools.exe
echo  Distribua a pasta dist\GCodeTools inteira.
echo ============================================================
pause
exit /b 0

:erro
echo.
echo ERRO: a geracao do executavel falhou. Veja as mensagens acima.
pause
exit /b 1
