"""Orchestration de l'instruction.

Pour chaque exigence encore ouverte du profil :
  1) on retrouve des passages candidats dans le corpus (retrieval simple) ;
  2) Albert QUALIFIE (proposition : statut_propose + preuves + confiance) ;
  3) on (re)crée le Constat sur sa couche IA — la couche RSSI reste vierge.
La reprise sur compléments ne rejoue QUE les exigences non encore validées par
le RSSI ; les exigences déjà tranchées ne sont pas écrasées.
"""
from __future__ import annotations

import re

from sqlmodel import Session, select

from . import llm, clausier_io
from .extraction import Bloc, extraire
from .models import (Constat, Demande, Document, Dossier, Evenement, ExigenceRef,
                     Preuve, Statut, StatutDemande)
from .referentiel import criticite_effective, exigences_du_profil
from pathlib import Path


def _corpus(session: Session, dossier_id: int) -> tuple[list[Bloc], list[str], dict[str, dict]]:
    """Renvoie (blocs texte libre, avertissements, réponses structurées par code).
    Une fiche de réponse SynAApCE remplie est lue de façon structurée (par code
    d'exigence), pas dépiautée en texte libre."""
    blocs: list[Bloc] = []
    avert: list[str] = []
    reponses: dict[str, dict] = {}
    for doc in session.exec(select(Document).where(Document.dossier_id == dossier_id)).all():
        p = Path(doc.chemin)
        if clausier_io.est_fiche_liaison(p):
            _dossier, rep = clausier_io.lire_fiche_liaison(p)
            reponses.update(rep)
        elif clausier_io.est_fiche_reponse(p):
            reponses.update(clausier_io.lire_fiche_reponse(p))
        else:
            r = extraire(p, nom_affiche=doc.nom)
            blocs.extend(r.blocs)
            avert.extend(r.avertissements)
    return blocs, avert, reponses


def _mots_cles(texte: str) -> set[str]:
    return {m for m in re.findall(r"[a-zàâçéèêëîïôûùüÿñæœ0-9]{4,}", texte.lower())}


# Lexique FR<->EN de sécurité : rend la recherche lexicale cross-langue (les dossiers
# éditeurs mêlent souvent français et anglais). Utilisé pour ENRICHIR la requête.
_LEXIQUE = {
    "chiffrement": ["encryption", "encrypted", "encrypt", "tls", "ssl"],
    "chiffrees": ["encryption", "encrypted"],
    "authentification": ["authentication", "login", "credentials"],
    "habilitation": ["authorization", "permission", "role", "access"],
    "habilitations": ["authorization", "permissions", "roles"],
    "sauvegarde": ["backup", "backups", "restore"],
    "sauvegardes": ["backup", "backups"],
    "restauration": ["restore", "recovery"],
    "journalisation": ["logging", "logs", "audit", "traceability"],
    "journaux": ["logs", "logging"],
    "cloisonnement": ["segmentation", "isolation", "vlan", "firewall"],
    "supervision": ["monitoring", "supervision"],
    "hebergement": ["hosting", "hosted", "datacenter", "cloud"],
    "reseau": ["network"],
    "serveur": ["server"],
    "mise": ["update", "patch", "patching"],
    "correctifs": ["patch", "patches", "update", "updates"],
    "vulnerabilite": ["vulnerability", "vulnerabilities", "cve"],
    "vulnerabilites": ["vulnerability", "vulnerabilities", "cve"],
    "disponibilite": ["availability", "uptime", "redundancy"],
    "integrite": ["integrity"],
    "confidentialite": ["confidentiality"],
    "donnees": ["data"],
    "utilisateur": ["user", "account"],
    "utilisateurs": ["users", "accounts"],
    "mot": ["password"],
    "passe": ["password"],
    "telemaintenance": ["remote", "maintenance"],
    "incident": ["incident", "breach"],
    "acces": ["access"],
    "pare-feu": ["firewall"],
    "antivirus": ["antivirus", "malware"],
    "certificat": ["certificate"],
}


def _cles_requete(question: str, criteres: list[str]) -> set[str]:
    """Mots-clés de la requête, enrichis de leurs équivalents FR<->EN de sécurité."""
    base = _mots_cles(question + " " + " ".join(criteres))
    enrichi = set(base)
    for m in base:
        for eq in _LEXIQUE.get(m, []):
            enrichi.update(_mots_cles(eq))
    return enrichi


_BRUIT = re.compile(
    r"(IBAN\b|\bBIC\b|\bRCS\b|SIREN|SAS au capital|Domiciliation bancaire|"
    r"Page\s+\d+\s+(sur|on)\s+\d+|\.{6,}|^[\s•\-–]+$)", re.I)


def _nettoyer(texte: str) -> str:
    """Retire les lignes de pied de page légal, marques de page et tables des matières
    qui polluent la recherche et diluent le contexte envoyé à Albert."""
    gardees = []
    for l in (texte or "").split("\n"):
        ll = l.strip()
        if not ll or _BRUIT.search(ll):
            continue
        # ligne quasi vide de sens (numéro de page seul, puces)
        if len(ll) <= 2:
            continue
        gardees.append(ll)
    return "\n".join(gardees)


def _decouper(blocs: list[Bloc], taille: int = 800, chevauchement: int = 150) -> list[dict]:
    """Découpe les blocs en passages courts, nettoyés et dédoublonnés."""
    passages: list[dict] = []
    vus: set[str] = set()

    def _ajouter(doc, page, section, texte):
        cle = re.sub(r"\s+", " ", texte.lower()).strip()[:200]
        if len(cle) < 40 or cle in vus:      # ignore trop court / doublon
            return
        vus.add(cle)
        passages.append({"document_nom": doc, "page": page, "section": section, "texte": texte})

    for b in blocs:
        t = _nettoyer(b.texte)
        if not t:
            continue
        if len(t) <= taille:
            _ajouter(b.document_nom, b.page, b.section, t)
            continue
        i = 0
        while i < len(t):
            _ajouter(b.document_nom, b.page, b.section, t[i:i + taille])
            i += taille - chevauchement
    return passages


def _cosinus(a: list[float], b: list[float]) -> float:
    import math
    s = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return s / (na * nb)


def _construire_index(passages: list[dict]) -> list[list[float]] | None:
    """Embeddings de tous les passages (une fois par analyse). None si indisponible."""
    if not passages:
        return None
    return llm.embeddings([p["texte"] for p in passages])


def _scores_lexicaux(question: str, criteres: list[str], passages: list[dict]) -> list[int]:
    cles = _cles_requete(question, criteres)
    notes = []
    for i, p in enumerate(passages):
        rec = len(cles & _mots_cles(p["texte"]))
        if rec:
            notes.append((rec, i))
    notes.sort(key=lambda x: x[0], reverse=True)
    return [i for _, i in notes]


def _retrouver_lexical(question: str, criteres: list[str], passages: list[dict], k: int) -> list[dict]:
    idx = _scores_lexicaux(question, criteres, passages)[:k]
    return [{"document_nom": passages[i]["document_nom"], "page": passages[i]["page"],
             "section": passages[i]["section"], "extrait": passages[i]["texte"][:900]} for i in idx]


def _retrouver(question: str, criteres: list[str], passages: list[dict],
               index: list[list[float]] | None = None, qvec: list[float] | None = None,
               k: int = 8, max_par_doc: int = 3) -> list[dict]:
    """Recherche HYBRIDE (sémantique ∪ lexicale) avec DIVERSITÉ entre documents :
    on plafonne le nombre de passages par document pour que plusieurs sources
    (ex. notice FR + architecture EN) parviennent à Albert."""
    sem: list[int] = []
    if index and qvec:
        scores = [(_cosinus(qvec, v), i) for i, v in enumerate(index)]
        scores.sort(key=lambda x: x[0], reverse=True)
        sem = [i for _, i in scores[:k * 2]]
    lex = _scores_lexicaux(question, criteres, passages)[:k * 2]

    ordre = list(dict.fromkeys(sem + lex))
    if not ordre:
        ordre = list(range(min(len(passages), k)))

    # diversité : au plus max_par_doc passages par document, puis on complète
    retenus, par_doc = [], {}
    for i in ordre:
        doc = passages[i]["document_nom"]
        if par_doc.get(doc, 0) < max_par_doc:
            retenus.append(i); par_doc[doc] = par_doc.get(doc, 0) + 1
        if len(retenus) >= k:
            break
    if len(retenus) < k:                     # compléter si pas assez de diversité
        for i in ordre:
            if i not in retenus:
                retenus.append(i)
            if len(retenus) >= k:
                break

    return [{"document_nom": passages[i]["document_nom"], "page": passages[i]["page"],
             "section": passages[i]["section"], "extrait": passages[i]["texte"][:900]}
            for i in retenus]


def analyser(session: Session, dossier: Dossier, acteur: str = "clausio",
             codes_cibles: set[str] | None = None) -> dict:
    """Analyse le dossier. Si codes_cibles est fourni, ne (ré)instruit que ces exigences."""
    blocs, avertissements, reponses = _corpus(session, dossier.id)
    exigences = exigences_du_profil(session, dossier.referentiel_version_id, dossier.profil)
    if codes_cibles is not None:
        exigences = [e for e in exigences if e.code in codes_cibles]

    dossier.analyse_total = len(exigences)
    dossier.analyse_faites = 0
    dossier.analyse_termine = False
    session.add(dossier)
    session.commit()

    # Index sémantique (embeddings Albert) construit une seule fois pour tout le corpus,
    # + embeddings des questions d'exigences en un lot. Repli lexical si indisponible.
    passages = _decouper(blocs)
    index = _construire_index(passages)
    if index:
        qtextes = [((e.question_rag or e.libelle) + " " + " ".join(e.criteres_acceptation or []))
                   for e in exigences]
        qvecs = llm.embeddings(qtextes)
    else:
        qvecs = None

    traitees, ignorees_validees = 0, 0
    for idx, ex in enumerate(exigences, start=1):
        constat = session.exec(
            select(Constat).where(
                Constat.dossier_id == dossier.id,
                Constat.exigence_ref_id == ex.id,
            )
        ).first()

        # On ne réécrit jamais une exigence déjà tranchée par le RSSI.
        if constat and constat.statut_valide is not None:
            ignorees_validees += 1
            dossier.analyse_faites = idx
            if idx % 5 == 0:
                session.add(dossier); session.commit()
            continue

        qvec = qvecs[idx - 1] if qvecs else None
        passages_ex = _retrouver(ex.question_rag or ex.libelle, ex.criteres_acceptation,
                                 passages, index, qvec)
        rep = reponses.get(ex.code)
        if rep and (rep.get("mesure") or rep.get("precisions")):
            # réponse structurée du candidat (fiche SynAApCE) = preuve prioritaire
            passages_ex = [{
                "document_nom": "Fiche de réponse SynAApCE",
                "page": None, "section": ex.code,
                "extrait": (f"Auto-appréciation candidat [{ex.code}] — Mesure : {rep.get('mesure','')}. "
                            f"Précisions : {rep.get('precisions','')}. "
                            f"Consolidation : {rep.get('consolidation','')}").strip(),
            }] + passages_ex
        prop = llm.confronter_exigence(ex.libelle, ex.question_rag, ex.criteres_acceptation, passages_ex)
        crit = criticite_effective(ex, dossier.profil)

        if not constat:
            constat = Constat(
                dossier_id=dossier.id,
                exigence_ref_id=ex.id,
                code_exigence=ex.code,
                axe=ex.axe,
                criticite_effective=crit,
            )
            session.add(constat)
            session.commit()
            session.refresh(constat)
        else:
            for p in session.exec(select(Preuve).where(Preuve.constat_id == constat.id)).all():
                session.delete(p)

        constat.criticite_effective = crit
        constat.statut_propose = Statut(prop.statut)
        constat.justification_ia = prop.justification
        constat.confiance_ia = prop.confiance
        session.add(constat)

        for p in prop.passages:
            session.add(Preuve(
                constat_id=constat.id,
                document_nom=p.get("document_nom", ""),
                page=p.get("page"),
                section=p.get("section", ""),
                extrait=(p.get("extrait", "") or "")[:600],
            ))
        session.commit()
        traitees += 1
        dossier.analyse_faites = idx
        if idx % 5 == 0:
            session.add(dossier); session.commit()

    dossier.analyse_faites = dossier.analyse_total
    dossier.analyse_termine = True
    session.add(dossier)
    _regenerer_demandes(session, dossier)
    session.add(Evenement(
        dossier_id=dossier.id, type="analyse", acteur=acteur,
        details={"exigences_traitees": traitees, "deja_validees": ignorees_validees,
                 "avertissements": avertissements},
    ))
    session.commit()
    return {"exigences_traitees": traitees, "deja_validees_rssi": ignorees_validees,
            "avertissements": avertissements}


def _regenerer_demandes(session: Session, dossier: Dossier) -> None:
    """Une demande de complément par constat non satisfait, numérotée.
    On lit d'abord la décision RSSI si elle existe, sinon la proposition IA."""
    for d in session.exec(select(Demande).where(Demande.dossier_id == dossier.id)).all():
        session.delete(d)
    session.commit()

    libelles = {e.id: e.libelle for e in session.exec(
        select(ExigenceRef).where(
            ExigenceRef.referentiel_version_id == dossier.referentiel_version_id)).all()}
    _motif = {Statut.absent: "non traité dans la candidature",
              Statut.partiel: "traité partiellement",
              Statut.a_verifier: "à confirmer / preuve non concluante"}

    constats = session.exec(select(Constat).where(Constat.dossier_id == dossier.id)).all()
    a_demander = {Statut.partiel, Statut.absent, Statut.a_verifier}
    numero = 0
    for c in sorted(constats, key=lambda x: x.code_exigence):
        statut = c.statut_valide if c.statut_valide is not None else c.statut_propose
        if statut in a_demander:
            numero += 1
            libelle = (libelles.get(c.exigence_ref_id, "") or "").strip()
            session.add(Demande(
                dossier_id=dossier.id, constat_id=c.id, numero=numero,
                code_exigence=c.code_exigence, libelle=libelle,
                texte=f"Élément {_motif.get(statut, statut.value)} — merci de compléter.",
                statut=StatutDemande.ouverte,
            ))
    session.commit()
