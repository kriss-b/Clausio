@echo off
REM Lanceur Clausio (Windows) - usage local. Config via .env ou variables d'environnement.
cd /d "%~dp0"
if not exist ".venv\Scripts\activate.bat" (
  echo [Clausio] Creation de l'environnement virtuel...
  py -3 -m venv .venv || python -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt
if "%HOST%"=="" set HOST=127.0.0.1
if "%PORT%"=="" set PORT=3000
echo [Clausio] Demarrage sur %HOST%:%PORT%  (Ctrl+C pour arreter)
start "" "http://127.0.0.1:%PORT%"
python -m uvicorn app.main:app --host %HOST% --port %PORT%
