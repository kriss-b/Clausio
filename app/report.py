"""Génération du rapport — accompagnée par le RSSI.

Le rapport lit la couche validée par le RSSI. Les exigences non encore tranchées
sont explicitement signalées « en attente de validation RSSI » : elles ne peuvent
pas fonder une conformité et laissent la conclusion en suspens. C'est la
traduction de « Clausio propose, le RSSI affine, puis génère ».
"""
from sqlmodel import Session, select

from .models import Constat, Demande, Dossier, Evenement, Preuve, Statut
from .scoring import score_par_axe, statut_blocage


def generer(session: Session, dossier: Dossier, acteur: str) -> dict:
    constats = session.exec(select(Constat).where(Constat.dossier_id == dossier.id)).all()
    demandes = session.exec(
        select(Demande).where(Demande.dossier_id == dossier.id).order_by(Demande.numero)
    ).all()

    non_validees = [c.code_exigence for c in constats if c.statut_valide is None]
    scores = score_par_axe(constats)
    blocage = statut_blocage(constats)

    if non_validees:
        conclusion = ("Projet de rapport — instruction incomplète : "
                      f"{len(non_validees)} exigence(s) restent à valider par le RSSI. "
                      "Aucune conclusion d'attribution ne peut être arrêtée en l'état.")
    elif blocage["attribution_possible"]:
        conclusion = ("Avis favorable envisageable au titre de la cybersécurité, "
                      "sous réserve de la levée des demandes de compléments listées.")
    else:
        conclusion = ("Avis défavorable en l'état : réserve(s) bloquante(s) non levée(s) "
                      f"— {', '.join(blocage['bloquants_non_leves'])}. "
                      "Convertible en avis favorable après levée des conditions numérotées.")

    lignes = []
    for c in sorted(constats, key=lambda x: x.code_exigence):
        preuves = session.exec(select(Preuve).where(Preuve.constat_id == c.id)).all()
        lignes.append({
            "code": c.code_exigence,
            "axe": c.axe,
            "criticite": c.criticite_effective.value,
            "statut_retenu": (c.statut_valide.value if c.statut_valide else "EN ATTENTE RSSI"),
            "propose_par_ia": c.statut_propose.value,
            "confiance_ia": c.confiance_ia,
            "commentaire_rssi": c.commentaire_rssi,
            "valide_par": c.valide_par,
            "preuves": [{"document": p.document_nom, "page": p.page,
                         "section": p.section, "extrait": p.extrait} for p in preuves],
        })

    session.add(Evenement(
        dossier_id=dossier.id, type="rapport", acteur=acteur,
        details={"conclusion": conclusion, "exigences_en_attente": non_validees},
    ))
    session.commit()

    return {
        "dossier": {"reference": dossier.reference_marche, "objet": dossier.objet,
                    "profil": dossier.profil},
        "genere_par": acteur,
        "conclusion": conclusion,
        "instruction_complete": not non_validees,
        "exigences_en_attente_rssi": non_validees,
        "score_par_axe": scores,
        "blocage": blocage,
        "constats": lignes,
        "demandes_complements": [
            {"numero": d.numero, "code": d.code_exigence, "libelle": d.libelle,
             "texte": d.texte, "statut": d.statut.value}
            for d in demandes
        ],
        "avertissement": ("Ce document est une pré-instruction outillée validée par le RSSI. "
                          "La décision d'attribution demeure humaine et motivée."),
    }
