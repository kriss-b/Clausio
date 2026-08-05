"""Persistance SQLite — un seul fichier .db, facile à sauvegarder/archiver
avec le dossier de marché (utile pour la traçabilité)."""
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

DB_PATH = Path(__file__).resolve().parent.parent / "clausio.db"
_engine = create_engine(
    f"sqlite:///{DB_PATH}", echo=False,
    connect_args={"check_same_thread": False, "timeout": 30},
)


def init_db() -> None:
    SQLModel.metadata.create_all(_engine)
    _ajouter_colonnes_manquantes()


def _ajouter_colonnes_manquantes() -> None:
    """Migration douce : ajoute les colonnes de métadonnées si une base existe déjà."""
    from sqlalchemy import text
    colonnes = {
        "societe_ou_produit": "TEXT DEFAULT ''",
        "contact_nom": "TEXT DEFAULT ''",
        "contact_email": "TEXT DEFAULT ''",
        "contact_tel": "TEXT DEFAULT ''",
        "type_dispositif": "TEXT DEFAULT ''",
        "resume_ia": "TEXT DEFAULT ''",
        "marche_nom": "TEXT DEFAULT ''",
        "marche_email": "TEXT DEFAULT ''",
        "marche_tel": "TEXT DEFAULT ''",
        "analyse_total": "INTEGER DEFAULT 0",
        "analyse_faites": "INTEGER DEFAULT 0",
        "analyse_termine": "INTEGER DEFAULT 1",
        "parent_id": "INTEGER",
        "owner_id": "INTEGER",
        "correspondant_id": "INTEGER",
    }
    with _engine.begin() as conn:
        existantes = {r[1] for r in conn.execute(text("PRAGMA table_info(dossier)"))}
        for nom, typ in colonnes.items():
            if nom not in existantes:
                conn.execute(text(f"ALTER TABLE dossier ADD COLUMN {nom} {typ}"))
        cols_demande = {r[1] for r in conn.execute(text("PRAGMA table_info(demande)"))}
        if "libelle" not in cols_demande:
            conn.execute(text("ALTER TABLE demande ADD COLUMN libelle TEXT DEFAULT ''"))
        cols_param = {r[1] for r in conn.execute(text("PRAGMA table_info(parametres)"))}
        if "logo_path" not in cols_param:
            conn.execute(text("ALTER TABLE parametres ADD COLUMN logo_path TEXT DEFAULT ''"))
        cols_constat = {r[1] for r in conn.execute(text("PRAGMA table_info(constat)"))}
        if "statut_declare" not in cols_constat:
            conn.execute(text("ALTER TABLE constat ADD COLUMN statut_declare TEXT"))
        cols_rv = {r[1] for r in conn.execute(text("PRAGMA table_info(referentielversion)"))}
        for nom, typ in {"description": "TEXT DEFAULT ''", "famille": "TEXT DEFAULT 'sante'",
                          "profils_disponibles": "JSON"}.items():
            if nom not in cols_rv:
                conn.execute(text(f"ALTER TABLE referentielversion ADD COLUMN {nom} {typ}"))


def get_session() -> Session:
    return Session(_engine)
