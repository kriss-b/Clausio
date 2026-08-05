"""Configuration de Clausio.

Toute la configuration passe par des VARIABLES D'ENVIRONNEMENT (ou un fichier `.env`
à la racine du projet). Aucune clé n'est stockée dans le code — le dépôt est public.

Fournisseur LLM : Clausio parle le protocole OpenAI (`/chat/completions`, `/embeddings`).
Il fonctionne donc avec n'importe quel service compatible :
  - Albert (plateforme souveraine DINUM) — valeur par défaut de l'URL ;
  - OpenAI, Mistral, Azure OpenAI, Groq, etc. ;
  - un LLM LOCAL : Ollama, vLLM, LM Studio, llama.cpp (aucune clé requise).

Voir `.env.example` et le README pour les exemples de configuration.
"""
import os
from pathlib import Path


def _charger_dotenv() -> None:
    """Charge un fichier .env (racine du projet) sans dépendance externe."""
    fichier = Path(__file__).resolve().parent.parent / ".env"
    if not fichier.exists():
        return
    for ligne in fichier.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#") or "=" not in ligne:
            continue
        cle, _, val = ligne.partition("=")
        os.environ.setdefault(cle.strip(), val.strip().strip('"').strip("'"))


_charger_dotenv()


def _env(*noms: str, defaut: str = "") -> str:
    for n in noms:
        v = os.getenv(n)
        if v:
            return v
    return defaut


# --- Fournisseur LLM (protocole OpenAI) --------------------------------------
# URL de base incluant le suffixe de version (ex. .../v1).
LLM_BASE_URL = _env("CLAUSIO_LLM_BASE_URL", "ALBERT_BASE_URL", "OPENAI_BASE_URL",
                    defaut="https://albert.api.etalab.gouv.fr/v1")
# Clé d'API. Laisser VIDE pour un LLM local (Ollama, vLLM, LM Studio...).
LLM_API_KEY = _env("CLAUSIO_LLM_API_KEY", "ALBERT_API_KEY", "OPENAI_API_KEY", defaut="")
# Modèle de génération. Vide = auto-détection via GET /models.
LLM_MODEL = _env("CLAUSIO_LLM_MODEL", "ALBERT_MODEL", "OPENAI_MODEL", defaut="")
# Modèle d'embeddings (recherche sémantique). Vide = auto-détection ; à forcer pour
# les LLM locaux (ex. "nomic-embed-text" sous Ollama).
LLM_EMBED_MODEL = _env("CLAUSIO_LLM_EMBED_MODEL", "ALBERT_EMBED_MODEL", defaut="")

# Alias de rétro-compatibilité (anciens scripts / variables ALBERT_*).
ALBERT_API_KEY = LLM_API_KEY
ALBERT_BASE_URL = LLM_BASE_URL
ALBERT_MODEL = LLM_MODEL

# --- Authentification de l'application ---------------------------------------
# Compte administrateur initial (créé au premier démarrage). À CHANGER.
DEV_UTILISATEUR = _env("CLAUSIO_USER", defaut="admin")
DEV_MOT_DE_PASSE = _env("CLAUSIO_PASSWORD", defaut="clausio2026!")

# Secret de signature des sessions. À REMPLACER par une longue chaîne aléatoire.
SESSION_SECRET = _env("CLAUSIO_SESSION_SECRET", defaut="clausio-secret-de-dev-a-changer")

# Version du build.
VERSION = "0.0.27"
