"""Stockage sécurisé des fichiers.

Objectifs :
- aucun nom prévisible sur le disque (répertoires et fichiers = jetons aléatoires)
  afin d'éviter les accès directs devinables (IDOR) ;
- aucune utilisation du nom de fichier fourni par le client comme chemin
  (protection contre le path traversal). Le nom d'origine n'est conservé que
  comme métadonnée d'affichage.
"""
from __future__ import annotations

import os
import re
import secrets
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
UPLOADS = BASE / "uploads"
EXPORTS = BASE / "exports"

# Plafond par fichier (Mo) — configurable via l'environnement.
MAX_UPLOAD_MO = int(os.getenv("CLAUSIO_MAX_UPLOAD_MO", "50"))
_EXT_OK = re.compile(r"\.[a-z0-9]{1,8}\Z")


def nouveau_ref() -> str:
    """Identifiant de répertoire non devinable pour un dossier."""
    return secrets.token_urlsafe(16)


def _ext(nom: str) -> str:
    e = os.path.splitext(nom or "")[1].lower()
    return e if _EXT_OK.match(e) else ""


def nom_affichage(nom: str) -> str:
    """Nom d'origine nettoyé, pour l'affichage uniquement (jamais un chemin)."""
    base = os.path.basename(nom or "").replace("\\", "").strip()
    return base[:180] or "document"


def nom_stocke(nom_origine: str) -> str:
    """Nom de fichier aléatoire sur le disque, en conservant l'extension."""
    return secrets.token_hex(16) + _ext(nom_origine)


def _ref_dossier(session, dossier_id: int) -> str:
    from .models import Dossier
    d = session.get(Dossier, dossier_id)
    ref = getattr(d, "stockage_ref", "") if d else ""
    return ref or str(dossier_id)   # repli pour d'anciens dossiers


def dir_uploads(session, dossier_id: int) -> Path:
    p = UPLOADS / _ref_dossier(session, dossier_id)
    p.mkdir(parents=True, exist_ok=True)
    return p


def dir_exports(session, dossier_id: int) -> Path:
    p = EXPORTS / _ref_dossier(session, dossier_id)
    p.mkdir(parents=True, exist_ok=True)
    return p


def taille_ok(data: bytes) -> bool:
    return len(data) <= MAX_UPLOAD_MO * 1024 * 1024
