"""Authentification multi-utilisateurs (comptes en base, mots de passe hachés).

Session signée (cookie). Un compte 'admin' est amorcé au démarrage à partir de
CLAUSIO_USER / CLAUSIO_PASSWORD (config.py). L'admin gère les autres comptes.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from typing import Optional

from fastapi import Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from .config import DEV_MOT_DE_PASSE, DEV_UTILISATEUR
from .database import get_session
from .models import Utilisateur

_ITER = 200_000


def hacher(mot_de_passe: str, salt: Optional[str] = None) -> tuple[str, str]:
    sel = bytes.fromhex(salt) if salt else os.urandom(16)
    h = hashlib.pbkdf2_hmac("sha256", mot_de_passe.encode("utf-8"), sel, _ITER)
    return sel.hex(), h.hex()


def verifier_mdp(mot_de_passe: str, salt: str, hash_hex: str) -> bool:
    if not salt or not hash_hex:
        return False
    _, h = hacher(mot_de_passe, salt)
    return hmac.compare_digest(h, hash_hex)


def assurer_admin() -> None:
    """Garantit qu'AU MOINS UN compte admin actif existe (sinon (re)crée/promeut
    le compte bootstrap CLAUSIO_USER). Évite de se retrouver sans accès admin."""
    with get_session() as s:
        admins = s.exec(select(Utilisateur).where(Utilisateur.role == "admin",
                                                  Utilisateur.actif == True)).all()  # noqa: E712
        if admins:
            return
        u = s.exec(select(Utilisateur).where(Utilisateur.username == DEV_UTILISATEUR)).first()
        if u:
            u.role = "admin"
            u.actif = True
            s.add(u)
        else:
            salt, h = hacher(DEV_MOT_DE_PASSE)
            s.add(Utilisateur(username=DEV_UTILISATEUR, nom="Administrateur", role="admin",
                              salt=salt, mot_de_passe_hash=h, actif=True))
        s.commit()


def verifier_identifiants(utilisateur: str, mot_de_passe: str) -> bool:
    with get_session() as s:
        u = s.exec(select(Utilisateur).where(Utilisateur.username == utilisateur)).first()
        return bool(u and u.actif and verifier_mdp(mot_de_passe, u.salt, u.mot_de_passe_hash))


def utilisateur_courant(request: Request) -> str | None:
    return request.session.get("utilisateur")


def utilisateur_obj(request: Request, session: Session) -> Optional[Utilisateur]:
    nom = request.session.get("utilisateur")
    if not nom:
        return None
    return session.exec(select(Utilisateur).where(Utilisateur.username == nom)).first()


def est_admin(request: Request, session: Session) -> bool:
    u = utilisateur_obj(request, session)
    return bool(u and u.role == "admin")


def _racine(session: Session, dossier):
    from .models import Dossier
    return session.get(Dossier, dossier.parent_id) if dossier.parent_id else dossier


def peut_voir(request: Request, session: Session, dossier) -> bool:
    """Visible par l'admin, le propriétaire (RSSI) ou le correspondant. Calcul sur la racine."""
    u = utilisateur_obj(request, session)
    if not u:
        return False
    if u.role == "admin":
        return True
    r = _racine(session, dossier)
    return r.owner_id == u.id or r.correspondant_id == u.id


def exiger_connexion(request: Request) -> RedirectResponse | None:
    if not utilisateur_courant(request):
        return RedirectResponse("/login", status_code=303)
    return None
