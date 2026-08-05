"""Pré-remplissage d'un dossier à partir des documents déposés.

Combine une extraction texte (PDF/Word/Excel/ZIP, OCR des scans via Albert en
extension) avec :
  - des expressions régulières fiables pour l'email et le téléphone ;
  - une extraction structurée par Albert pour société/produit, contact, type de
    dispositif et un résumé de première analyse.
Tout est PROPOSÉ : le RSSI relit et corrige avant de créer le dossier.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import llm
from .extraction import extraire

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_TEL = re.compile(r"(?:(?:\+33|0)\s?[1-9])(?:[\s.\-]?\d{2}){4}")

_TYPES = ["logiciel", "materiel_biomedical", "dispositif_medical_connecte",
          "service_heberge", "materiel_non_medical", "autre"]

_SYSTEME = (
    "Tu extrais des métadonnées d'un dossier de candidature à un marché public "
    "hospitalier, à partir d'un extrait de document. N'invente rien : laisse vide "
    "si l'information n'est pas présente. Réponds STRICTEMENT en JSON : "
    '{"societe_ou_produit": "", "contact_nom": "", "contact_email": "", '
    '"contact_telephone": "", "type_dispositif": "un parmi: '
    + "|".join(_TYPES) + '", "resume": "3 à 4 phrases neutres décrivant l\'objet et '
    'les points saillants cybersécurité"}'
)


def pre_remplir(chemins: list[Path]) -> dict:
    textes, avertissements = [], []
    for c in chemins:
        r = extraire(c)
        textes.extend(b.texte for b in r.blocs)
        avertissements.extend(r.avertissements)
    corpus = "\n".join(textes)

    # Repli déterministe (toujours calculé, sert aussi de garde-fou)
    emails = _EMAIL.findall(corpus)
    tels = _TEL.findall(corpus)
    base = {
        "societe_ou_produit": "",
        "contact_nom": "",
        "contact_email": emails[0] if emails else "",
        "contact_telephone": re.sub(r"\s+", " ", tels[0]).strip() if tels else "",
        "type_dispositif": "",
        "resume": "",
        "profil_suggere": "socle",
        "source": "hors_ligne",
        "avertissements": avertissements,
    }

    if llm.disponible() and corpus.strip():
        data = llm.chat_json(_SYSTEME, corpus[:8000])
        if data:
            for k in ("societe_ou_produit", "contact_nom", "type_dispositif"):
                if data.get(k):
                    base[k] = str(data[k]).strip()
            # email/tel : on garde la regex si Albert est vide ou incohérent
            if data.get("contact_email") and _EMAIL.fullmatch(str(data["contact_email"]).strip()):
                base["contact_email"] = str(data["contact_email"]).strip()
            if data.get("contact_telephone"):
                base["contact_telephone"] = str(data["contact_telephone"]).strip()
            if data.get("resume"):
                base["resume"] = str(data["resume"]).strip()
            base["source"] = "albert"

    base["profil_suggere"] = (
        "dispositif_medical"
        if base["type_dispositif"] in ("materiel_biomedical", "dispositif_medical_connecte")
        else "socle"
    )
    return base
