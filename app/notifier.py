"""Notifications par courriel (SMTP).

Optionnel : activé et configuré dans l'administration. Sert notamment à prévenir
les personnes qui instruisent un dossier lorsqu'il est mis à jour (liste des
changements + lien vers le dossier). Envoi best-effort en tâche de fond : une
panne SMTP ne bloque jamais l'application.
"""
from __future__ import annotations

import smtplib
import ssl
import threading
from email.message import EmailMessage
from email.utils import formataddr

from sqlmodel import select

from .database import get_session
from .models import Configuration, Dossier, ExigenceRef, Utilisateur


def _cfg():
    with get_session() as s:
        c = s.get(Configuration, 1)
        if c:
            s.expunge(c)
        return c


def _envoyer_sync(cfg: Configuration, destinataires: list[str], sujet: str, html: str) -> tuple[bool, str]:
    dests = [d for d in dict.fromkeys(destinataires) if d and "@" in d]
    if not dests:
        return False, "Aucun destinataire valide."
    msg = EmailMessage()
    msg["Subject"] = sujet
    msg["From"] = formataddr(("Clausio", cfg.smtp_from or cfg.smtp_user))
    msg["To"] = ", ".join(dests)
    msg.set_content("Votre client de messagerie n'affiche pas le HTML.")
    msg.add_alternative(html, subtype="html")
    try:
        if cfg.smtp_securite == "ssl":
            with smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port or 465,
                                  context=ssl.create_default_context(), timeout=20) as srv:
                if cfg.smtp_user:
                    srv.login(cfg.smtp_user, cfg.smtp_password)
                srv.send_message(msg)
        else:
            with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port or 587, timeout=20) as srv:
                if cfg.smtp_securite == "starttls":
                    srv.starttls(context=ssl.create_default_context())
                if cfg.smtp_user:
                    srv.login(cfg.smtp_user, cfg.smtp_password)
                srv.send_message(msg)
        return True, ""
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:200]


def tester(destinataire: str) -> dict:
    cfg = _cfg()
    if not (cfg and cfg.smtp_host):
        return {"ok": False, "erreur": "SMTP non configuré."}
    ok, err = _envoyer_sync(
        cfg, [destinataire], "Clausio — test de configuration SMTP",
        "<p>Ceci est un courriel de test envoyé par Clausio. "
        "Si vous le recevez, la configuration SMTP fonctionne.</p>")
    return {"ok": ok, "erreur": err}


def _lien_dossier(cfg: Configuration, dossier_id: int) -> str:
    base = (cfg.app_base_url or "").rstrip("/")
    return f"{base}/dossiers/{dossier_id}" if base else f"/dossiers/{dossier_id}"


def notifier_maj_dossier(dossier_id: int, changements: list[dict], auteur: str = "") -> None:
    """Prévient les personnes du dossier d'une mise à jour (tâche de fond)."""
    cfg = _cfg()
    if not (cfg and cfg.smtp_actif and cfg.smtp_host):
        return

    def _job():
        with get_session() as s:
            d = s.get(Dossier, dossier_id)
            if not d:
                return
            racine = s.get(Dossier, d.parent_id) if d.parent_id else d
            emails = []
            for uid in (racine.owner_id, racine.correspondant_id):
                if uid:
                    u = s.get(Utilisateur, uid)
                    if u and u.email and u.username != auteur:
                        emails.append(u.email)
        if not emails:
            return
        lignes = "".join(
            f"<li><strong>{c.get('code','')}</strong> : "
            f"{c.get('avant','?')} &rarr; {c.get('apres','?')}</li>"
            for c in changements[:60])
        lien = _lien_dossier(cfg, racine.id)
        html = (f"<p>Le dossier <strong>{d.nom_affiche}</strong> vient d'être mis à jour"
                + (f" par {auteur}" if auteur else "") + ".</p>"
                f"<p>Changements ({len(changements)}) :</p><ul>{lignes}</ul>"
                f'<p><a href="{lien}">Ouvrir le dossier dans Clausio</a></p>'
                "<p style='color:#666;font-size:12px'>Message automatique — Clausio.</p>")
        _envoyer_sync(cfg, emails, f"[Clausio] Mise à jour du dossier {d.nom_affiche}", html)

    threading.Thread(target=_job, daemon=True).start()
