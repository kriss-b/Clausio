"""Notation déterministe.

Deux résultats SÉPARÉS, calculés par des règles (pas par l'IA) et sur la seule
couche validée par le RSSI :
  1) un score par axe (indicatif) ;
  2) un statut de blocage indépendant.

Règle d'or : une exigence BLOQUANTE non couverte interdit toute recommandation
d'attribution, quel que soit le score. Un bon score ne « rachète » jamais un
bloquant. Une exigence non tranchée par le RSSI est traitée comme non satisfaite.
"""
from collections import defaultdict

from .models import Constat, Criticite, Statut

# Points par statut retenu
_POINTS = {
    Statut.couvert: 1.0,
    Statut.partiel: 0.5,
    Statut.absent: 0.0,
    Statut.a_verifier: 0.0,
    Statut.non_evalue: 0.0,
    # non_applicable : exclu du calcul
}
# Poids par criticité
_POIDS = {Criticite.bloquant: 3, Criticite.majeur: 2, Criticite.mineur: 1}


def score_par_axe(constats: list[Constat]) -> dict:
    agg: dict[str, dict] = defaultdict(lambda: {"num": 0.0, "den": 0.0, "n": 0})
    for c in constats:
        statut = c.statut_valide if c.statut_valide is not None else Statut.non_evalue
        if statut == Statut.non_applicable:
            continue
        poids = _POIDS[c.criticite_effective]
        a = agg[c.axe]
        a["num"] += _POIDS[c.criticite_effective] * _POINTS.get(statut, 0.0)
        a["den"] += poids
        a["n"] += 1
    return {
        axe: {"score": round(100 * v["num"] / v["den"], 1) if v["den"] else None,
              "exigences": v["n"]}
        for axe, v in agg.items()
    }


def statut_blocage(constats: list[Constat]) -> dict:
    """Renvoie l'état de blocage et la liste des bloquants non levés."""
    non_leves = []
    en_attente_validation = []
    for c in constats:
        if c.criticite_effective != Criticite.bloquant:
            continue
        if c.statut_valide is None:
            en_attente_validation.append(c.code_exigence)
            non_leves.append(c.code_exigence)
        elif c.statut_valide not in (Statut.couvert, Statut.non_applicable):
            non_leves.append(c.code_exigence)

    return {
        "attribution_possible": len(non_leves) == 0,
        "bloquants_non_leves": non_leves,
        "bloquants_en_attente_validation_rssi": en_attente_validation,
    }


# Axes du référentiel rattachés aux mesures de gestion des risques NIS2 (art. 21).
NIS2_AXES = {"gouvernance", "sous_traitance", "logiciels", "identites", "authentification",
             "tracabilite", "protection_systemes", "cryptographie", "maintenance",
             "developpement", "hebergement", "reseau_wifi"}

# Axes rattachés aux obligations RGPD (sous-traitance/DPA art. 28, sécurité art. 32,
# violation art. 33, traçabilité/registre, hébergement/transferts, confidentialité santé).
RGPD_AXES = {"sous_traitance", "protection_donnees_medicales", "tracabilite",
             "hebergement", "cryptographie", "authentification"}


def _indicateur(constats: list[Constat], axes: set[str] | None) -> dict:
    """axes=None => sur toutes les exigences (indicateur global pondéré)."""
    num = den = 0.0
    n = 0
    for c in constats:
        if axes is not None and c.axe not in axes:
            continue
        statut = c.statut_valide if c.statut_valide is not None else c.statut_propose
        if statut == Statut.non_applicable:
            continue
        poids = _POIDS[c.criticite_effective]
        num += poids * _POINTS.get(statut, 0.0)
        den += poids
        n += 1
    score = round(100 * num / den) if den else 0
    couleur = "vert" if score >= 80 else ("orange" if score >= 50 else "rouge")
    return {"score": score, "couleur": couleur, "exigences": n}


def indicateur_global(constats: list[Constat]) -> dict:
    """Score de conformité global (0-100), pondéré par la criticité, toutes exigences."""
    return _indicateur(constats, None)


def indicateur_nis2(constats: list[Constat]) -> dict:
    """Indicateur INDICATIF d'alignement NIS2 (0-100) + couleur, sur les axes
    rattachables aux mesures de l'article 21. Pas une mesure officielle de conformité."""
    return _indicateur(constats, NIS2_AXES)


def indicateur_rgpd(constats: list[Constat]) -> dict:
    """Indicateur INDICATIF de conformité RGPD (0-100) + couleur, sur les axes
    rattachables aux obligations du règlement. Pas un avis DPO."""
    return _indicateur(constats, RGPD_AXES)
