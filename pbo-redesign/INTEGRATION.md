# PBO UI Redesign — Integration Guide

## Fichiers livrés

```
pbo-redesign/
├── styles.css          → remplace apps/web/src/styles.css
├── AppShell.tsx        → remplace apps/web/src/components/AppShell.tsx
├── DashboardPage.tsx   → remplace apps/web/src/pages/DashboardPage.tsx
├── StatCard.tsx        → remplace apps/web/src/components/StatCard.tsx
├── AuthContext.tsx     → nouveau  apps/web/src/AuthContext.tsx
├── LoginPage.tsx       → nouveau  apps/web/src/pages/LoginPage.tsx
├── App.tsx             → remplace apps/web/src/App.tsx
├── api.ts              → remplace apps/web/src/api.ts
├── auth.py             → nouveau  apps/api/app/auth.py
├── router.py           → remplace apps/api/app/api/router.py
└── index.html          → remplace apps/web/index.html
```

---

## 1. Frontend — Dépendances

Aucune nouvelle dépendance npm requise.
GSAP et Google Fonts sont chargés depuis CDN dans `index.html`.

Si tu veux installer GSAP en local (recommandé pour la prod offline) :
```bash
cd apps/web
npm install gsap
```
Puis dans `AppShell.tsx` et `DashboardPage.tsx`, retire le `declare const gsap: any`
et remplace par `import gsap from "gsap"`.

---

## 2. Backend — Dépendances Python

Ajouter dans `apps/api/pyproject.toml` (section `[project.dependencies]`) :

```toml
"python-jose[cryptography]>=3.3.0",
"passlib[bcrypt]>=1.7.4",
"python-multipart>=0.0.9",
```

---

## 3. Variables d'environnement (`.env`)

Ajouter au fichier `.env` (copie de `.env.example`) :

```env
# ── Authentication ──────────────────────────────────────
AUTH_ENABLED=true

# Nom d'utilisateur admin
AUTH_USERNAME=admin

# Hash bcrypt du mot de passe — générer avec :
#   python -c "from passlib.hash import bcrypt; print(bcrypt.hash('votre_mot_de_passe'))"
AUTH_PASSWORD_HASH=$2b$12$REMPLACER_PAR_VOTRE_HASH

# Clé secrète JWT — utiliser une chaîne aléatoire longue :
#   python -c "import secrets; print(secrets.token_hex(32))"
AUTH_SECRET_KEY=REMPLACER_PAR_UNE_CHAINE_ALEATOIRE_LONGUE

# Durée de vie du token en minutes (défaut : 480 = 8h)
AUTH_TOKEN_EXPIRE_MINUTES=480
```

---

## 4. Générer un hash de mot de passe

```bash
# Dans le container Docker ou localement avec Python
python3 -c "from passlib.hash import bcrypt; print(bcrypt.hash('mon_mot_de_passe'))"
```

Copier le hash affiché dans `AUTH_PASSWORD_HASH`.

---

## 5. Intégration dans main.py (FastAPI)

Dans `apps/api/app/main.py`, importer le nouveau router :

```python
# Remplacer
from app.api.router import api_router
# Par
from app.api.router import api_router  # (router.py mis à jour — rien à changer ici)
```

Le fichier `router.py` livré expose déjà `api_router` — l'import ne change pas.

---

## 6. Désactiver l'auth en développement

```env
AUTH_ENABLED=false
```

Quand `AUTH_ENABLED=false` :
- Le backend accepte toutes les requêtes sans token
- Le frontend affiche quand même la page de login (comportement voulu pour le test UI)
- Pour ignorer totalement le login côté front en dev, passer `AUTH_ENABLED=false`
  ET commenter le guard dans `App.tsx` :
  ```tsx
  // if (!isAuthenticated) return <LoginPage t={t} />;
  ```

---

## 7. Comportement de session

- Le token JWT est stocké dans `sessionStorage` (disparaît à la fermeture de l'onglet)
- Durée par défaut : 8h (configurable via `AUTH_TOKEN_EXPIRE_MINUTES`)
- Si le token expire, toute requête API retourne 401 → déconnexion automatique + redirect login
- Pas de refresh token (usage local, relogin manuel acceptable)

---

## 8. Sécurité — notes pour déploiement local

- L'app est conçue pour un réseau local (LAN) — **ne pas exposer sur internet sans HTTPS**
- Pour HTTPS en local, utiliser un reverse proxy (Nginx, Caddy) avec un certificat auto-signé
- Le `AUTH_SECRET_KEY` doit être différent entre installations
- Changer le mot de passe par défaut immédiatement

---

## 9. Design system — personnalisation rapide

Toutes les couleurs sont des CSS variables dans `styles.css` (section `:root`) :

```css
--accent:    #00c8ff;   /* Cyan électrique — couleur principale */
--success:   #00e87a;   /* Vert */
--danger:    #ff4060;   /* Rouge */
--warning:   #ffbe00;   /* Jaune */
--bg-void:   #050b12;   /* Fond le plus sombre */
```

Pour changer le thème, modifier uniquement ces variables.

---

## 10. Animations GSAP — désactiver si nécessaire

Les animations sont conditionnelles (`if (typeof gsap === "undefined") return`).
Si GSAP n'est pas chargé (ex: pas d'accès CDN), l'interface fonctionne normalement sans animations.

Pour désactiver globalement, retirer les balises `<script>` GSAP dans `index.html`.
