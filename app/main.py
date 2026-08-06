"""API HTTP de Clausio (FastAPI).

Cycle : créer un dossier -> déposer des documents -> analyser (Albert propose)
-> le RSSI affine chaque constat -> générer le rapport. La reprise se fait en
redéposant des compléments puis en relançant l'analyse (seules les exigences
non validées sont rejouées).

Lancer :  uvicorn app.main:app --reload
Docs   :  http://127.0.0.1:8000/docs
"""
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Request, Depends, FastAPI, File, Form, HTTPException, UploadFile
from sqlmodel import Session, select
import os
from starlette.middleware.sessions import SessionMiddleware

from . import analysis, auth, report, web
from .config import SESSION_SECRET, VERSION
from .database import get_session, init_db
from .models import (Constat, Demande, Document, Dossier, Evenement, PhaseDocument,
                     ReferentielVersion, Statut, StatutDemande, StatutDossier)
from .referentiel import charger_referentiels

app = FastAPI(title="Clausio", version=VERSION)
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    same_site="lax",                       # atténue le CSRF
    https_only=os.getenv("CLAUSIO_HTTPS_ONLY", "0") == "1",  # à activer derrière HTTPS
    max_age=60 * 60 * 12,                  # 12 h
)
app.include_router(web.router)
UPLOADS = Path(__file__).resolve().parent.parent / "uploads"


def session_dep():
    with get_session() as s:
        yield s


@app.on_event("startup")
def _demarrage() -> None:
    init_db()
    UPLOADS.mkdir(exist_ok=True)
    from . import auth
    auth.preparer_demarrage()
    with get_session() as s:
        charger_referentiels(s)


@app.middleware("http")
async def _garde_installation(request: Request, call_next):
    """Tant que l'installation n'est pas faite, tout est redirigé vers l'assistant."""
    from . import settings
    chemin = request.url.path
    autorises = chemin.startswith("/installation") or chemin.startswith("/api/health") \
        or chemin.startswith("/static")
    try:
        faite = settings.installation_faite()
    except Exception:  # noqa: BLE001
        faite = True
    if not faite and not autorises:
        from starlette.responses import RedirectResponse
        return RedirectResponse("/installation", status_code=303)
    if faite and chemin.startswith("/installation"):
        from starlette.responses import RedirectResponse
        return RedirectResponse("/", status_code=303)
    return await call_next(request)


@app.get("/api/health")
def sante():
    return {"clausio": "ok", "docs": "/docs",
            "principe": "Clausio propose, le RSSI affine, la décision reste humaine."}


@app.get("/referentiels")
def lister_referentiels(s: Session = Depends(session_dep)):
    return s.exec(select(ReferentielVersion)).all()


@app.post("/dossiers")
def creer_dossier(reference_marche: str = Form(...), objet: str = Form(...),
                  profil: str = Form("socle"), referentiel_version_id: int = Form(...),
                  s: Session = Depends(session_dep)):
    if not s.get(ReferentielVersion, referentiel_version_id):
        raise HTTPException(404, "Version de référentiel inconnue.")
    d = Dossier(reference_marche=reference_marche, objet=objet, profil=profil,
                referentiel_version_id=referentiel_version_id)
    s.add(d)
    s.commit()
    s.refresh(d)
    return d


@app.post("/dossiers/{dossier_id}/documents")
async def deposer_documents(dossier_id: int, request: Request, phase: str = Form("initiale"),
                            fichiers: list[UploadFile] = File(...),
                            s: Session = Depends(session_dep)):
    from . import storage
    dossier = s.get(Dossier, dossier_id)
    if not dossier or not auth.peut_voir(request, s, dossier):
        raise HTTPException(404, "Dossier inconnu.")
    dest = storage.dir_uploads(s, dossier_id)
    crees = []
    for f in fichiers:
        data = await f.read()
        if not storage.taille_ok(data):
            raise HTTPException(413, f"Fichier trop volumineux (max {storage.MAX_UPLOAD_MO} Mo).")
        affichage = storage.nom_affichage(f.filename)
        chemin = dest / storage.nom_stocke(f.filename)      # nom aléatoire non prévisible
        chemin.write_bytes(data)
        doc = Document(dossier_id=dossier_id, nom=affichage,
                       type=(affichage.rsplit(".", 1)[-1] if "." in affichage else ""),
                       chemin=str(chemin), phase=PhaseDocument(phase))
        s.add(doc)
        crees.append(doc)
    if phase == PhaseDocument.complement.value:
        dossier.statut = StatutDossier.en_instruction
        s.add(dossier)
    s.commit()
    return {"deposes": len(crees)}


@app.post("/dossiers/{dossier_id}/analyser")
def lancer_analyse(dossier_id: int, s: Session = Depends(session_dep)):
    dossier = s.get(Dossier, dossier_id)
    if not dossier:
        raise HTTPException(404, "Dossier inconnu.")
    dossier.statut = StatutDossier.en_instruction
    s.add(dossier)
    s.commit()
    return analysis.analyser(s, dossier)


@app.get("/dossiers/{dossier_id}/constats")
def lister_constats(dossier_id: int, request: Request, s: Session = Depends(session_dep)):
    d = s.get(Dossier, dossier_id)
    if not d or not auth.peut_voir(request, s, d):
        raise HTTPException(403, "Accès refusé.")
    return s.exec(select(Constat).where(Constat.dossier_id == dossier_id)).all()


@app.patch("/constats/{constat_id}")
def valider_constat(constat_id: int, request: Request, statut_valide: str = Form(...),
                    commentaire_rssi: str = Form(""), valide_par: str = Form(...),
                    s: Session = Depends(session_dep)):
    """Décision du RSSI : c'est ici qu'il affine la proposition de Clausio."""
    c = s.get(Constat, constat_id)
    if not c:
        raise HTTPException(404, "Constat inconnu.")
    d = s.get(Dossier, c.dossier_id)
    if not d or not auth.peut_voir(request, s, d):
        raise HTTPException(403, "Accès refusé.")
    try:
        nouveau = Statut(statut_valide)
    except ValueError:
        raise HTTPException(422, f"Statut invalide : {statut_valide}")

    c.statut_valide = nouveau
    c.commentaire_rssi = commentaire_rssi
    c.valide_par = valide_par
    c.valide_at = datetime.now(timezone.utc)
    c.updated_at = c.valide_at
    s.add(c)

    # Lever la demande de complément si l'exigence est désormais couverte / N.A.
    for d in s.exec(select(Demande).where(Demande.constat_id == constat_id)).all():
        d.statut = (StatutDemande.levee if nouveau in (Statut.couvert, Statut.non_applicable)
                    else StatutDemande.ouverte)
        s.add(d)

    s.add(Evenement(dossier_id=c.dossier_id, type="validation_rssi", acteur=valide_par,
                    details={"constat": c.code_exigence, "statut": nouveau.value,
                             "propose_ia": c.statut_propose.value}))
    s.commit()
    s.refresh(c)
    return c


@app.get("/dossiers/{dossier_id}/demandes")
def lister_demandes(dossier_id: int, request: Request, s: Session = Depends(session_dep)):
    d0 = s.get(Dossier, dossier_id)
    if not d0 or not auth.peut_voir(request, s, d0):
        raise HTTPException(403, "Accès refusé.")
    return s.exec(
        select(Demande).where(Demande.dossier_id == dossier_id).order_by(Demande.numero)
    ).all()


@app.post("/dossiers/{dossier_id}/rapport")
def generer_rapport(dossier_id: int, request: Request, genere_par: str = Form(...),
                    s: Session = Depends(session_dep)):
    dossier = s.get(Dossier, dossier_id)
    if not dossier or not auth.peut_voir(request, s, dossier):
        raise HTTPException(403, "Accès refusé.")
    return report.generer(s, dossier, acteur=genere_par)


@app.get("/dossiers/{dossier_id}/journal")
def journal(dossier_id: int, request: Request, s: Session = Depends(session_dep)):
    dj = s.get(Dossier, dossier_id)
    if not dj or not auth.peut_voir(request, s, dj):
        raise HTTPException(403, "Accès refusé.")
    return s.exec(
        select(Evenement).where(Evenement.dossier_id == dossier_id).order_by(Evenement.at)
    ).all()
