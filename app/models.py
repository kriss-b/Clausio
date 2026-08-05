"""
Schéma de données Clausio.

Principe directeur : « Clausio propose, le RSSI affine ».
Chaque exigence évaluée sur un dossier donne un Constat qui porte DEUX couches :
  - la couche IA   : statut_propose / justification_ia / confiance_ia / preuves
  - la couche RSSI : statut_valide / commentaire_rssi / valide_par / valide_at
Le rapport et la conclusion d'attribution ne lisent QUE la couche RSSI.
Tant qu'une exigence n'est pas validée par le RSSI, elle est « en attente »
et ne peut pas fonder une conformité.

Le référentiel est une DONNÉE VERSIONNÉE (ReferentielVersion -> ExigenceRef),
pas du code : on peut le faire évoluer sans toucher au moteur, et on garde la
trace de la version qui a servi à instruire chaque dossier.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------
# Vocabulaire contrôlé
# --------------------------------------------------------------------------
class Criticite(str, Enum):
    bloquant = "bloquant"
    majeur = "majeur"
    mineur = "mineur"


class Statut(str, Enum):
    non_evalue = "non_evalue"        # pas encore instruit
    couvert = "couvert"              # exigence satisfaite, preuve à l'appui
    partiel = "partiel"              # partiellement satisfaite
    absent = "absent"                # non traité dans la candidature
    non_applicable = "non_applicable"
    a_verifier = "a_verifier"        # l'IA n'a pas tranché : arbitrage humain requis


class PhaseDocument(str, Enum):
    initiale = "initiale"            # candidature reçue
    complement = "complement"        # réponse aux demandes de compléments


class StatutDossier(str, Enum):
    ouvert = "ouvert"
    en_instruction = "en_instruction"
    en_attente_complements = "en_attente_complements"
    clos = "clos"


class StatutDemande(str, Enum):
    ouverte = "ouverte"
    levee = "levee"


# --------------------------------------------------------------------------
# Référentiel versionné
# --------------------------------------------------------------------------
class ReferentielVersion(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    ref_id: str = Field(index=True)                 # ex. "socle"
    version: str                                    # ex. "2026.1"
    libelle: str
    description: str = ""
    famille: str = "sante"                          # regroupement du catalogue
    date_maj: Optional[str] = None
    sources: list = Field(default_factory=list, sa_column=Column(JSON))
    profils_disponibles: dict = Field(default_factory=dict, sa_column=Column(JSON))



class ExigenceRef(SQLModel, table=True):
    """Une exigence du référentiel. Immuable une fois chargée : on ne la modifie
    pas, on publie une nouvelle version du référentiel."""
    id: Optional[int] = Field(default=None, primary_key=True)
    referentiel_version_id: int = Field(foreign_key="referentielversion.id", index=True)

    code: str = Field(index=True)                   # ex. "NIS2-SC-01"
    axe: str                                         # axe de sécurité
    libelle: str
    source: str                                      # base réglementaire
    profils: list = Field(default_factory=list, sa_column=Column(JSON))  # ["socle", "dispositif_medical"]

    criticite_defaut: Criticite = Criticite.majeur
    # surcharge éventuelle par profil : {"dispositif_medical": "bloquant"}
    criticite_par_profil: dict = Field(default_factory=dict, sa_column=Column(JSON))
    applicable_des: Optional[str] = None             # ex. "2027-12" (trajectoire CRA)

    question_rag: str = ""                           # ce que l'on cherche dans la candidature
    criteres_acceptation: list = Field(default_factory=list, sa_column=Column(JSON))



# --------------------------------------------------------------------------
# Dossier d'instruction
# --------------------------------------------------------------------------
class Dossier(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    reference_marche: str
    objet: str
    profil: str = "socle"                            # profil d'évaluation retenu
    referentiel_version_id: int = Field(foreign_key="referentielversion.id")
    statut: StatutDossier = StatutDossier.ouvert
    created_at: datetime = Field(default_factory=_now)

    # Métadonnées pré-remplies par l'analyse (OCR + Albert), éditables par le RSSI
    societe_ou_produit: str = ""                     # sert de nom d'affichage du dossier
    contact_nom: str = ""
    contact_email: str = ""
    contact_tel: str = ""
    type_dispositif: str = ""                         # logiciel, materiel_biomedical, ...
    resume_ia: str = ""                               # première analyse du document

    # Personne du service marchés de l'établissement qui a transmis le dossier
    marche_nom: str = ""
    marche_email: str = ""
    marche_tel: str = ""

    # Suivi de l'analyse (pour l'affichage de l'avancement en temps réel)
    analyse_total: int = 0
    analyse_faites: int = 0
    analyse_termine: bool = True

    # Analyses liées : un dossier « racine » (parent_id=None) + des analyses d'autres
    # référentiels rattachées (RGPD pour la DPO, MDR pour le biomed, etc.).
    parent_id: Optional[int] = Field(default=None, foreign_key="dossier.id", index=True)

    # Cloisonnement : propriétaire (RSSI qui instruit) + correspondant établissement (liaison).
    owner_id: Optional[int] = Field(default=None, index=True)
    correspondant_id: Optional[int] = Field(default=None, index=True)

    @property
    def nom_affiche(self) -> str:
        return self.societe_ou_produit or self.objet or self.reference_marche


class Document(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    dossier_id: int = Field(foreign_key="dossier.id", index=True)
    nom: str
    type: str = ""                                   # pdf, docx, xlsx, txt...
    chemin: str                                      # emplacement local du fichier
    phase: PhaseDocument = PhaseDocument.initiale
    uploaded_at: datetime = Field(default_factory=_now)


class Constat(SQLModel, table=True):
    """Le cœur : une exigence évaluée sur un dossier, avec ses deux couches."""
    id: Optional[int] = Field(default=None, primary_key=True)
    dossier_id: int = Field(foreign_key="dossier.id", index=True)
    exigence_ref_id: int = Field(foreign_key="exigenceref.id", index=True)
    code_exigence: str = Field(index=True)           # dénormalisé pour lisibilité
    axe: str = ""
    criticite_effective: Criticite = Criticite.majeur

    # --- couche IA (Albert) : proposition ---
    statut_propose: Statut = Statut.non_evalue
    justification_ia: str = ""
    confiance_ia: Optional[float] = None             # 0..1

    # --- couche RSSI : décision (fait foi) ---
    statut_valide: Optional[Statut] = None           # None = pas encore tranché
    commentaire_rssi: str = ""
    valide_par: Optional[str] = None
    valide_at: Optional[datetime] = None

    # --- position déclarée par le candidat via le fichier de liaison ---
    statut_declare: Optional[Statut] = None

    updated_at: datetime = Field(default_factory=_now)


    @property
    def statut_retenu(self) -> Statut:
        """Ce qui fait foi : la décision RSSI si elle existe, sinon 'en attente'."""
        return self.statut_valide if self.statut_valide is not None else Statut.non_evalue

    @property
    def valide_rssi(self) -> bool:
        return self.statut_valide is not None


class Preuve(SQLModel, table=True):
    """Traçabilité : chaque constat pointe vers le passage source de la candidature."""
    id: Optional[int] = Field(default=None, primary_key=True)
    constat_id: int = Field(foreign_key="constat.id", index=True)
    document_id: Optional[int] = Field(default=None, foreign_key="document.id")
    document_nom: str = ""
    page: Optional[int] = None
    section: str = ""
    extrait: str = ""                                # citation courte du passage



class Demande(SQLModel, table=True):
    """Demande de complément dérivée d'un constat partiel/absent/à vérifier.
    Mappe sur la logique de réserves numérotées et liftables."""
    id: Optional[int] = Field(default=None, primary_key=True)
    dossier_id: int = Field(foreign_key="dossier.id", index=True)
    constat_id: int = Field(foreign_key="constat.id")
    numero: int
    code_exigence: str = ""
    libelle: str = ""                                # intitulé complet de l'exigence
    texte: str
    statut: StatutDemande = StatutDemande.ouverte
    created_at: datetime = Field(default_factory=_now)


class Evenement(SQLModel, table=True):
    """Journal horodaté : qui a fait quoi, quand. Indispensable à la défendabilité."""
    id: Optional[int] = Field(default=None, primary_key=True)
    dossier_id: int = Field(foreign_key="dossier.id", index=True)
    type: str                                        # ex. "analyse", "validation_rssi", "rapport"
    acteur: str = ""
    details: dict = Field(default_factory=dict, sa_column=Column(JSON))
    at: datetime = Field(default_factory=_now)


class Parametres(SQLModel, table=True):
    """Paramètres de l'établissement et coordonnées du RSSI (ligne unique id=1).
    Repris dans les rapports et les fichiers de liaison."""
    id: Optional[int] = Field(default=1, primary_key=True)
    etablissement: str = ""
    rssi_nom: str = ""
    rssi_email: str = ""
    rssi_tel: str = ""
    logo_path: str = ""                              # logo de l'établissement (repris dans le PDF)


class Utilisateur(SQLModel, table=True):
    """Compte utilisateur. role: 'admin' (gère les comptes, voit tout) ou 'utilisateur'."""
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True)
    nom: str = ""
    email: str = ""
    role: str = "utilisateur"
    salt: str = ""
    mot_de_passe_hash: str = ""
    actif: bool = True
    created_at: datetime = Field(default_factory=_now)
