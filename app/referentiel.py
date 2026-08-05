"""Chargement du moteur de référentiel depuis les fichiers YAML.

Le référentiel est une donnée : on le charge en base, versionné. Le rechargement
est idempotent (même ref_id + même version => on ne recrée pas). Pour faire
évoluer un référentiel (ex. abrogation d'une délibération), on publie une NOUVELLE
version dans le YAML ; les dossiers déjà instruits restent liés à leur version.
"""
from pathlib import Path

import yaml
from sqlmodel import Session, select

from .models import Criticite, ExigenceRef, ReferentielVersion

REFERENTIELS_DIR = Path(__file__).resolve().parent.parent / "referentiels"


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
