"""Accès à la configuration applicative (table Configuration, ligne unique).

La configuration du LLM et de l'authentification est renseignée par l'assistant
d'installation. Les valeurs de config.py (.env) servent de repli.
"""
from __future__ import annotations

from typing import Optional

from sqlmodel import Session, select

from . import config
from .database import get_session
from .models import Configuration


def charger_config(session: Session) -> Configuration:
    cfg = session.get(Configuration, 1)
    if not cfg:
        cfg = Configuration(id=1)
        session.add(cfg)
        session.commit()
        session.refresh(cfg)
    return cfg


def installation_faite() -> bool:
    with get_session() as s:
        cfg = charger_config(s)
        return bool(cfg.installation_faite)


def llm_effectif() -> dict:
    """Réglages LLM effectifs : valeur en base si renseignée, sinon .env/config.py."""
    with get_session() as s:
        cfg = charger_config(s)
    return {
        "base_url": cfg.llm_base_url or config.LLM_BASE_URL,
        "api_key": cfg.llm_api_key or config.LLM_API_KEY,
        "model": cfg.llm_model or config.LLM_MODEL,
        "embed_model": cfg.llm_embed_model or config.LLM_EMBED_MODEL,
        "temperature": cfg.llm_temperature if cfg.llm_temperature is not None else 0.0,
    }


def auth_config() -> Optional[Configuration]:
    with get_session() as s:
        cfg = charger_config(s)
        s.expunge(cfg)
        return cfg
