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


def preparer_demarrage() -> None:
    """Au démarrage : marque comme « installé » tout déploiement existant (comptes déjà
    présents), et garantit un admin actif UNIQUEMENT si l'installation est faite.
    Sur une base vierge, on laisse l'assistant d'installation créer le premier compte."""
    from .models import Configuration
    with get_session() as s:
        cfg = s.get(Configuration, 1)
        if not cfg:
            cfg = Configuration(id=1)
            s.add(cfg); s.commit(); s.refresh(cfg)
        comptes = s.exec(select(Utilisateur)).first()
        if comptes and not cfg.installation_faite:
            cfg.installation_faite = True     # déploiement pré-existant : pas de wizard
            s.add(cfg); s.commit()
        if not cfg.installation_faite:
            return                            # base vierge -> assistant d'installation
        # installation faite : garantir un admin actif
        admin = s.exec(select(Utilisateur).where(Utilisateur.role == "admin",
                                                 Utilisateur.actif == True)).first()  # noqa: E712
        if admin:
            return
        u = s.exec(select(Utilisateur).where(Utilisateur.username == DEV_UTILISATEUR)).first()
        if u:
            u.role = "admin"; u.actif = True; s.add(u)
        else:
            salt, h = hacher(DEV_MOT_DE_PASSE)
            s.add(Utilisateur(username=DEV_UTILISATEUR, nom="Administrateur", role="admin",
                              salt=salt, mot_de_passe_hash=h, actif=True))
        s.commit()


# rétro-compat
def assurer_admin() -> None:
    preparer_demarrage()


def _verifier_local(utilisateur: str, mot_de_passe: str) -> bool:
    with get_session() as s:
        u = s.exec(select(Utilisateur).where(Utilisateur.username == utilisateur)).first()
        return bool(u and u.actif and u.mot_de_passe_hash
                    and verifier_mdp(mot_de_passe, u.salt, u.mot_de_passe_hash))


def _provisionner_ldap(utilisateur: str) -> None:
    """Crée un compte local (sans mot de passe) pour un utilisateur LDAP au 1er login,
    afin que la propriété des dossiers et la visibilité fonctionnent."""
    with get_session() as s:
        if not s.exec(select(Utilisateur).where(Utilisateur.username == utilisateur)).first():
            s.add(Utilisateur(username=utilisateur, nom=utilisateur, role="utilisateur",
                              actif=True, salt="", mot_de_passe_hash=""))
            s.commit()


def _verifier_ldap(utilisateur: str, mot_de_passe: str) -> bool:
    """Bind LDAP/AD (expérimental). Nécessite le paquet ldap3. Échec silencieux -> False."""
    from . import settings
    cfg = settings.auth_config()
    if not (cfg and cfg.auth_mode == "ldap" and cfg.ldap_host and cfg.ldap_bind_template):
        return False
    if not mot_de_passe:
        return False
    try:
        import ldap3  # type: ignore
    except Exception:  # noqa: BLE001
        return False
    try:
        dn = cfg.ldap_bind_template.format(login=utilisateur, username=utilisateur)
        serveur = ldap3.Server(cfg.ldap_host, port=cfg.ldap_port or 389,
                               use_ssl=bool(cfg.ldap_use_tls), get_info=None)
        conn = ldap3.Connection(serveur, user=dn, password=mot_de_passe, auto_bind=True)
        ok = bool(conn.bound)
        conn.unbind()
        if ok:
            _provisionner_ldap(utilisateur)
        return ok
    except Exception:  # noqa: BLE001
        return False


def verifier_identifiants(utilisateur: str, mot_de_passe: str) -> bool:
    # Les comptes locaux (dont l'admin) fonctionnent toujours : jamais de verrouillage.
    if _verifier_local(utilisateur, mot_de_passe):
        return True
    return _verifier_ldap(utilisateur, mot_de_passe)


def mfa_verifier(secret: str, code: str) -> bool:
    """Vérifie un code TOTP (Google Authenticator, FreeOTP, Aegis…)."""
    if not (secret and code):
        return False
    try:
        import pyotp
        return bool(pyotp.TOTP(secret).verify((code or "").replace(" ", "").strip(), valid_window=1))
    except Exception:  # noqa: BLE001
        return False


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
