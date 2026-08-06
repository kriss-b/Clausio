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
        cols_cfg = {r[1] for r in conn.execute(text("PRAGMA table_info(configuration)"))}
        if cols_cfg and "llm_temperature" not in cols_cfg:
            conn.execute(text("ALTER TABLE configuration ADD COLUMN llm_temperature FLOAT DEFAULT 0.0"))
        # stockage_ref : répertoire de stockage non devinable
        if "stockage_ref" not in existantes:
            conn.execute(text("ALTER TABLE dossier ADD COLUMN stockage_ref TEXT DEFAULT ''"))
        import secrets as _sec
        for (did,) in conn.execute(text("SELECT id FROM dossier WHERE stockage_ref IS NULL OR stockage_ref=''")):
            conn.execute(text("UPDATE dossier SET stockage_ref=:r WHERE id=:i"),
                         {"r": _sec.token_urlsafe(16), "i": did})
        cols_u = {r[1] for r in conn.execute(text("PRAGMA table_info(utilisateur)"))}
        if cols_u and "mfa_secret" not in cols_u:
            conn.execute(text("ALTER TABLE utilisateur ADD COLUMN mfa_secret TEXT DEFAULT ''"))
        if cols_u and "mfa_active" not in cols_u:
            conn.execute(text("ALTER TABLE utilisateur ADD COLUMN mfa_active BOOLEAN DEFAULT 0"))
        if cols_cfg and "ref_repo_url" not in cols_cfg:
            conn.execute(text("ALTER TABLE configuration ADD COLUMN ref_repo_url TEXT DEFAULT ''"))
        for col, typ in {"smtp_actif":"BOOLEAN DEFAULT 0","smtp_host":"TEXT DEFAULT ''",
                          "smtp_port":"INTEGER DEFAULT 587","smtp_user":"TEXT DEFAULT ''",
                          "smtp_password":"TEXT DEFAULT ''","smtp_from":"TEXT DEFAULT ''",
                          "smtp_securite":"TEXT DEFAULT 'starttls'","app_base_url":"TEXT DEFAULT ''"}.items():
            if cols_cfg and col not in cols_cfg:
                conn.execute(text(f"ALTER TABLE configuration ADD COLUMN {col} {typ}"))
        for col in ("tel_fixe","tel_mobile"):
            if cols_u and col not in cols_u:
                conn.execute(text(f"ALTER TABLE utilisateur ADD COLUMN {col} TEXT DEFAULT ''"))


def get_session() -> Session:
    return Session(_engine)
