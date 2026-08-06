"""Chargement du moteur de référentiel depuis les fichiers YAML.

Le référentiel est une donnée : on le charge en base, versionné. Le rechargement
est idempotent (même ref_id + même version => on ne recrée pas). Pour faire
évoluer un référentiel (ex. abrogation d'une délibération), on publie une NOUVELLE
version dans le YAML ; les dossiers déjà instruits restent liés à leur version.
"""
from pathlib import Path
import re

import httpx
import yaml
from sqlmodel import Session, select

from .models import Criticite, ExigenceRef, ReferentielVersion

REFERENTIELS_DIR = Path(__file__).resolve().parent.parent / "referentiels"

_RE_TREE = re.compile(r"https?://github\.com/([^/]+)/([^/]+)/tree/([^/]+)(?:/(.+))?/?$")
_RE_NOM_SUR = re.compile(r"[^A-Za-z0-9._-]")


def maj_depuis_github(session: Session, url: str,
                      dossier: Path = REFERENTIELS_DIR) -> dict:
    """Télécharge les référentiels YAML depuis un dépôt GitHub et les (re)charge.

    `url` : lien « tree » du dossier, ex.
    https://github.com/nocomp/Clausio/tree/main/referentiels
    Sécurité : seuls les fichiers .yaml/.yml sont écrits, sous un nom nettoyé
    (jamais de chemin), et le contenu est validé comme YAML avant écriture.
    """
    m = _RE_TREE.match((url or "").strip())
    if not m:
        return {"ok": False, "erreur": "URL GitHub invalide (attendu .../tree/<branche>/<chemin>)."}
    owner, repo, branch, chemin = m.group(1), m.group(2), m.group(3), (m.group(4) or "")
    api = f"https://api.github.com/repos/{owner}/{repo}/contents/{chemin}"
    entetes = {"Accept": "application/vnd.github+json"}
    import os as _os
    token = _os.getenv("CLAUSIO_GITHUB_TOKEN", "")     # optionnel : lève la limite 60/h
    if token:
        entetes["Authorization"] = f"Bearer {token}"
    try:
        r = httpx.get(api, params={"ref": branch}, headers=entetes,
                      timeout=30, follow_redirects=True)
        if r.status_code == 403 and r.headers.get("x-ratelimit-remaining") == "0":
            return {"ok": False, "erreur": "Limite de requêtes GitHub atteinte (60/h). "
                    "Réessayez plus tard, ou définissez CLAUSIO_GITHUB_TOKEN pour l'augmenter."}
        r.raise_for_status()
        items = r.json()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "erreur": f"Accès GitHub impossible : {str(e)[:150]}"}
    if not isinstance(items, list):
        return {"ok": False, "erreur": "Chemin introuvable dans le dépôt."}

    dossier.mkdir(parents=True, exist_ok=True)
    telecharges = 0
    for it in items:
        nom = it.get("name", "")
        if not nom.endswith((".yaml", ".yml")) or it.get("type") != "file":
            continue
        dl = it.get("download_url")
        if not dl:
            continue
        try:
            c = httpx.get(dl, timeout=30, follow_redirects=True)
            c.raise_for_status()
            data = yaml.safe_load(c.text)          # valide que c'est du YAML
            if not isinstance(data, dict) or "referentiel" not in data:
                continue
            sur = _RE_NOM_SUR.sub("_", nom)         # nom de fichier sûr, sans chemin
            (dossier / sur).write_text(c.text, encoding="utf-8")
            telecharges += 1
        except Exception:  # noqa: BLE001
            continue

    charges = charger_referentiels(session, dossier)
    return {"ok": True, "telecharges": telecharges, "total": len(charges)}


def charger_referentiels(session: Session, dossier: Path = REFERENTIELS_DIR) -> list[ReferentielVersion]:
    charges: list[ReferentielVersion] = []
    for fichier in sorted(dossier.glob("*.yaml")):
        data = yaml.safe_load(fichier.read_text(encoding="utf-8"))
        meta = data["referentiel"]

        existe = session.exec(
            select(ReferentielVersion).where(
                ReferentielVersion.ref_id == meta["id"],
                ReferentielVersion.version == str(meta["version"]),
            )
        ).first()
        if existe:
            charges.append(existe)
            continue

        rv = ReferentielVersion(
            ref_id=meta["id"],
            version=str(meta["version"]),
            libelle=meta.get("libelle", meta["id"]),
            description=meta.get("description", ""),
            famille=meta.get("famille", "sante"),
            date_maj=meta.get("date_maj"),
            sources=meta.get("sources", []),
            profils_disponibles=meta.get("profils_disponibles", {"socle": "Socle"}),
        )
        session.add(rv)
        session.commit()
        session.refresh(rv)

        for ex in data.get("exigences", []):
            session.add(
                ExigenceRef(
                    referentiel_version_id=rv.id,
                    code=ex["code"],
                    axe=ex["axe"],
                    libelle=ex["libelle"],
                    source=ex.get("source") or ex.get("source_specifique") or rv.libelle,
                    profils=ex.get("profils", ["socle"]),
                    criticite_defaut=Criticite(ex.get("criticite_defaut", "majeur")),
                    criticite_par_profil=ex.get("criticite_par_profil", {}),
                    applicable_des=ex.get("applicable_des"),
                    question_rag=ex.get("question_rag", ""),
                    criteres_acceptation=ex.get("criteres_acceptation", []),
                )
            )
        session.commit()
        charges.append(rv)
    return charges


def exigences_du_profil(session: Session, referentiel_version_id: int, profil: str) -> list[ExigenceRef]:
    """Les exigences activées pour un profil donné (socle, dispositif_medical, ...)."""
    toutes = session.exec(
        select(ExigenceRef).where(ExigenceRef.referentiel_version_id == referentiel_version_id)
    ).all()
    return [e for e in toutes if profil in (e.profils or [])]


def criticite_effective(exigence: ExigenceRef, profil: str) -> Criticite:
    """La criticité peut être renforcée selon le profil (ex. HDS devient bloquant
    en contexte dispositif médical avec données de santé)."""
    surcharge = (exigence.criticite_par_profil or {}).get(profil)
    return Criticite(surcharge) if surcharge else exigence.criticite_defaut
