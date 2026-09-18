@echo off
rem ---------------------------------------------------------------------------
rem  TrafficVolumes - spusteni zadavani intenzit
rem
rem  Polozte tento soubor vedle slozky "trafficvolumes" a vedle projektoveho
rem  souboru *.tvol. Po dvojkliku se otevre prohlizec s mapou.
rem  Potreba je pouze nainstalovany Python 3.9 nebo novejsi.
rem ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"

set PROJEKT=%~1
if "%PROJEKT%"=="" for %%F in (*.tvol) do set PROJEKT=%%F

if "%PROJEKT%"=="" (
  echo V teto slozce neni zadny soubor *.tvol.
  echo Pretahnete projektovy soubor na tento .bat, nebo jej sem zkopirujte.
  pause
  exit /b 1
)

where py >nul 2>nul && (set PY=py -3) || (set PY=python)

echo Spoustim TrafficVolumes nad projektem %PROJEKT% ...
%PY% -m trafficvolumes serve "%PROJEKT%" --open
if errorlevel 1 (
  echo.
  echo Neco se nepovedlo. Zkontrolujte, ze je nainstalovany Python 3.9+
  echo ^(https://www.python.org/downloads/ - zaskrtnete "Add Python to PATH"^).
  pause
)
