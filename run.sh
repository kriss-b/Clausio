#!/usr/bin/env bash
# Lanceur Clausio (Linux / macOS) — À LANCER SANS sudo.
# Configuration via variables d'environnement ou fichier .env (voir .env.example).
set -e
cd "$(dirname "$0")"

PY=""
for cand in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$cand" >/dev/null 2>&1; then
    if "$cand" -c 'import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)' 2>/dev/null; then
      PY="$(command -v "$cand")"; break
    fi
  fi
done
if [ -z "$PY" ]; then
  echo "[Clausio] Python 3.10+ requis. Ubuntu : sudo apt install -y python3.12 python3.12-venv" >&2
  exit 1
fi
PYVER="$("$PY" -c 'import sys;print(f"{sys.version_info.major}.{sys.version_info.minor}")')"

if [ -d ".venv" ] && [ ! -f ".venv/bin/activate" ]; then rm -rf .venv; fi
creer_venv() {
  if "$PY" -m venv .venv 2>/tmp/clausio_venv_err; then return 0; fi
  rm -rf .venv
  if command -v virtualenv >/dev/null 2>&1 && virtualenv -p "$PY" .venv 2>>/tmp/clausio_venv_err; then return 0; fi
  rm -rf .venv; return 1
}
if [ ! -d ".venv" ]; then
  echo "[Clausio] Création de l'environnement virtuel (Python $PYVER)…"
  if ! creer_venv; then
    echo "[Clausio] Échec du venv. Installez : sudo apt install -y python${PYVER}-venv  (ou python3-virtualenv)" >&2
    sed 's/^/    /' /tmp/clausio_venv_err >&2 || true
    exit 1
  fi
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt

# Rappel configuration LLM (via .env ou variables d'environnement) :
if [ -z "${CLAUSIO_LLM_API_KEY:-}${ALBERT_API_KEY:-}${OPENAI_API_KEY:-}" ] && [ ! -f ".env" ]; then
  echo "[Clausio] ⚠ Aucun LLM configuré. Copiez .env.example vers .env et renseignez-le,"
  echo "          ou exportez CLAUSIO_LLM_BASE_URL / CLAUSIO_LLM_API_KEY / CLAUSIO_LLM_MODEL."
  echo "          (Sans LLM, l'analyse tourne mais tout reste en « à vérifier ».)"
fi

HOST="${HOST:-0.0.0.0}"; PORT="${PORT:-3000}"
echo "[Clausio] Démarrage sur ${HOST}:${PORT}  (Ctrl+C pour arrêter)"
if [ "$HOST" = "0.0.0.0" ]; then
  IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
  echo "[Clausio] Local  : http://127.0.0.1:${PORT}"
  [ -n "$IP" ] && echo "[Clausio] Réseau : http://${IP}:${PORT}  (ouvrez le pare-feu si besoin)"
fi
if [ -n "${DISPLAY:-}" ] && [ "$HOST" != "0.0.0.0" ]; then
  ( sleep 2; command -v xdg-open >/dev/null && xdg-open "http://127.0.0.1:${PORT}" ) &
fi
exec python -m uvicorn app.main:app --host "$HOST" --port "$PORT"
