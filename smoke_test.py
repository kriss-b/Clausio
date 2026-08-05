"""Test bout-en-bout hors ligne : crée un dossier, dépose une candidature .txt,
analyse (Albert stub), le RSSI valide un constat, génère le rapport."""
from fastapi.testclient import TestClient
from app.main import app
from pathlib import Path
import io, json

import contextlib
_ctx = TestClient(app)
c = _ctx.__enter__()

# candidature factice
cand = ("Notre offre inclut une politique de divulgation coordonnee des vulnerabilites (CVD) "
        "avec correction sous 30 jours. L'hebergement est assure par un hebergeur certifie HDS. "
        "MFA active pour tous les comptes administrateurs. TLS 1.3 impose.")

refs = c.get("/referentiels").json()
rid = refs[0]["id"]
print("Referentiel:", refs[0]["ref_id"], refs[0]["version"], "id=", rid)

d = c.post("/dossiers", data={"reference_marche":"2026-DPI-01","objet":"Renouvellement DPI",
           "profil":"dispositif_medical","referentiel_version_id":rid}).json()
did = d["id"]
print("Dossier cree id=", did, "profil=", d["profil"])

r = c.post(f"/dossiers/{did}/documents", data={"phase":"initiale"},
           files={"fichiers": ("candidature.txt", io.BytesIO(cand.encode()), "text/plain")})
print("Depot:", r.json())

a = c.post(f"/dossiers/{did}/analyser").json()
print("Analyse:", {k:a[k] for k in ("exigences_traitees","deja_validees_rssi")})

constats = c.get(f"/dossiers/{did}/constats").json()
print(f"Constats generes: {len(constats)}  (couche RSSI vide au depart)")
hds = [x for x in constats if x["code_exigence"]=="HDS-01"][0]
print("  HDS-01 criticite effective (profil DM):", hds["criticite_effective"],
      "| statut_valide:", hds["statut_valide"])

# rapport AVANT validation RSSI -> instruction incomplete
rap = c.post(f"/dossiers/{did}/rapport", data={"genere_par":"rssi.test"}).json()
print("Rapport (avant validation): complete =", rap["instruction_complete"],
      "| en attente:", len(rap["exigences_en_attente_rssi"]))
print("  conclusion:", rap["conclusion"][:90], "...")

# le RSSI tranche HDS-01 en 'couvert'
c.patch(f"/constats/{hds['id']}", data={"statut_valide":"couvert",
        "commentaire_rssi":"Certificat HDS verifie","valide_par":"rssi.test"})
print("RSSI a valide HDS-01 -> couvert")

# verifier le blocage isole
rap2 = c.post(f"/dossiers/{did}/rapport", data={"genere_par":"rssi.test"}).json()
print("Blocage:", rap2["blocage"])
print("Score par axe (extrait):", {k:v["score"] for k,v in list(rap2["score_par_axe"].items())[:3]})
print("Demandes de complements:", len(rap2["demandes_complements"]))
print("Journal evenements:", len(c.get(f"/dossiers/{did}/journal").json()))
print("\nOK — le squelette tourne bout en bout.")
