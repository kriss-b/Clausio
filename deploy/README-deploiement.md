# Héberger Clausio pour le faire essayer (sans installation côté collègues)

Objectif : une URL que vos collègues RSSI ouvrent dans un navigateur.

## Recette recommandée : Caddy (HTTPS auto) + service systemd

1. **Installer Clausio** sur le VPS et créer le venv une fois : `bash run.sh` (Ctrl+C après le démarrage).
2. **Service systemd** (Clausio tourne en fond, redémarre tout seul) :
   ```bash
   # adapter User/chemins/secrets dans le fichier
   sudo cp deploy/clausio.service /etc/systemd/system/clausio.service
   sudo systemctl daemon-reload
   sudo systemctl enable --now clausio
   sudo systemctl status clausio
   ```
   uvicorn écoute alors en local sur 127.0.0.1:3000.
3. **DNS** : créez un enregistrement A `clausio.mondomaine.fr` → IP publique du VPS.
4. **Caddy** (HTTPS automatique) :
   ```bash
   sudo apt install -y caddy
   sudo cp deploy/Caddyfile /etc/caddy/Caddyfile   # remplacer le domaine
   sudo systemctl restart caddy
   ```
5. **Pare-feu** : n'ouvrez que 80 et 443 (Caddy), pas 3000.
   ```bash
   sudo ufw allow OpenSSH
   sudo ufw allow 80,443/tcp
   sudo ufw enable
   ```
   (Ouvrez aussi 80/443 dans le pare-feu de l'hébergeur si présent.)

Vos collègues vont sur `https://clausio.mondomaine.fr` et se connectent avec les identifiants
que vous leur communiquez.

## Sans domaine : Tailscale Funnel ou accès tailnet
- Accès réservé à vos collègues déjà sur votre tailnet : `http://<ip-tailscale>:3000`.
- Exposition publique via Tailscale Funnel : `tailscale funnel 3000` (HTTPS fourni par Tailscale).

## ⚠️ À lire avant de partager (important)
- **Une seule instance = données partagées.** Aujourd'hui, tous les utilisateurs partagent le même
  compte et voient les mêmes dossiers. Pour un essai à plusieurs, soit vous utilisez des **données
  d'exemple / anonymisées**, soit il faut activer des **comptes séparés avec cloisonnement** (à demander).
- **Ne déposez pas de vraies candidatures ni de données de santé** sur une instance de démonstration
  non durcie.
- **Clé Albert partagée** : tous les essais consomment votre quota Albert avec la même clé.
- Changez `CLAUSIO_USER` / `CLAUSIO_PASSWORD` / `CLAUSIO_SESSION_SECRET` avant toute mise en ligne.
