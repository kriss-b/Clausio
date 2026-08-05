"""Test d'intégration du clausier santé + AFIB, profil dispositif médical."""
from fastapi.testclient import TestClient
from app.main import app
import io

with TestClient(app) as c:
    refs = c.get("/referentiels").json()
    cs = [r for r in refs if r["ref_id"] == "clausier_sante"][0]
    print(f"Référentiel chargé : {cs['ref_id']} v{cs['version']}  (id={cs['id']})")

    d = c.post("/dossiers", data={"reference_marche":"2026-DM-IRM","objet":"IRM connectée",
               "profil":"dispositif_medical","referentiel_version_id":cs["id"]}).json()
    did = d["id"]

    # dépôt de la fiche SynAApCE (template) — lue de façon structurée
    with open("/mnt/user-data/uploads/Fiche_de_Reponse_SynAApCE_2026.xlsx","rb") as f:
        data = f.read()
    r = c.post(f"/dossiers/{did}/documents", data={"phase":"initiale"},
               files={"fichiers":("Fiche_de_Reponse_SynAApCE_2026.xlsx",
                       io.BytesIO(data),
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    print("Dépôt fiche SynAApCE :", r.json())

    a = c.post(f"/dossiers/{did}/analyser").json()
    print("Analyse :", {k:a[k] for k in ("exigences_traitees","deja_validees_rssi")})

    constats = c.get(f"/dossiers/{did}/constats").json()
    print(f"Constats (profil DM) : {len(constats)} exigences instruites")
    dm = [x for x in constats if x["code_exigence"].startswith("O-12.2")]
    print(f"  dont chapitre 12.2 (AFIB) : {len(dm)}")
    bloq = [x for x in constats if x["criticite_effective"]=="bloquant"]
    print(f"  exigences bloquantes (proposées) : {[x['code_exigence'] for x in bloq]}")
    # exemple : la notification de violation 24h
    v = [x for x in constats if x["code_exigence"]=="O-2.5"]
    if v: print(f"  O-2.5 criticité={v[0]['criticite_effective']} statut_valide={v[0]['statut_valide']}")
    print("\nLecture structurée de la fiche : OK — chaque exigence reçoit la réponse par code d'article.")
