Hyperflo Control - tableau de bord d'administration du serveur
===============================================================

Fichiers
--------
- app.py             : creation de FastAPI et branchement des modules
- config.py          : configuration et variables d'environnement
- auth.py            : login (mot de passe + TOTP), middleware, CSRF, anti brute-force
- sessions.py        : sessions cote serveur (revocables)
- security.py        : en-tetes HTTP, limite de taille des requetes, journal d'audit
- system_monitor.py  : CPU, RAM, GPU, disques, reseau et liste Docker
- docker_api.py      : start/stop/restart/details/logs Docker
- ollama_api.py      : Ollama, streaming, thinking et recherche Web
- pages.py           : routes HTML + menu commun (insere a la place de <!-- hyperflo:nav -->)
- static/common.css  : theme, menu et composants partages
- static/common.js   : fonctions partagees (Hyperflo.formatBytes, apiJson...)
- static/security.js : jeton CSRF, deconnexion, retour au login si session expiree
- tests/             : tests (lances par check.sh)
- check.sh           : verification complete avant redemarrage
- deploy/            : fichiers systeme (systemd, sudoers, scripts sudo) + install.sh

Modele de securite
------------------
Tout est fait sur le serveur, sans service externe.

- Acces: Cloudflare Tunnel -> cloudflared local -> Uvicorn sur 127.0.0.1:8080.
- Connexion: utilisateur + mot de passe argon2 + code TOTP.
  * Un code TOTP ne peut servir qu'une fois.
  * 5 echecs par IP sur 15 min -> IP bloquee.
  * 30 echecs au total sur 15 min -> toutes les connexions bloquees
    (protege contre une attaque distribuee). Une session ouverte peut lever
    le blocage depuis /admin; sinon redemarrer le service.
  * L'IP vient de CF-Connecting-IP, uniquement si la connexion est locale.
- Sessions: jeton aleatoire dans un cookie __Host- (HttpOnly, Secure,
  SameSite=Strict), stocke cote serveur. Expiration apres 1 h d'inactivite
  et 12 h au maximum. Revocables depuis /admin. Un redemarrage du service
  deconnecte tout le monde.
- CSRF: chaque requete qui modifie quelque chose doit porter l'en-tete
  X-Hyperflo-CSRF (static/security.js s'en charge). Les requetes venant d'un
  autre site, ou d'un autre sous-domaine, sont refusees (Sec-Fetch-Site).
- En-tetes: CSP stricte (aucun script ni style inline), anti-iframe,
  no-store sur les pages et l'API, HSTS.
- Docker: le service n'a acces qu'a trois scripts via sudo, qui valident
  l'action et le nom du conteneur.
- Audit: connexions, echecs, actions Docker, lectures de logs, sessions
  revoquees... dans journald et sur la page /admin:
    journalctl -u hyperflo-control | grep hyperflo-audit
  Un echec avec password_ok="True" et totp_ok="False" signifie que le mot de
  passe est probablement connu d'un tiers: le changer.

Pourquoi pas fail2ban: tout le trafic arrive de cloudflared (127.0.0.1), un
bannissement au niveau du pare-feu ne viserait pas l'attaquant. La limitation
est donc faite dans l'application.

Variables d'environnement (/etc/hyperflo-control.env)
-----------------------------------------------------
Obligatoires:
  HYPERFLO_USER, HYPERFLO_PASSWORD_HASH (argon2), HYPERFLO_TOTP_SECRET (base32),
  HYPERFLO_SESSION_SECRET (au moins 32 caracteres aleatoires)
Optionnelles (valeurs par defaut):
  OLLAMA_URL=http://127.0.0.1:11434, OLLAMA_API_KEY (recherche Web)
  HYPERFLO_SESSION_IDLE_TIMEOUT=3600, HYPERFLO_SESSION_MAX_AGE=43200,
  HYPERFLO_SESSION_MAX_COUNT=10
  HYPERFLO_LOGIN_WINDOW=900, HYPERFLO_LOGIN_MAX_FAILURES_PER_IP=5,
  HYPERFLO_LOGIN_MAX_FAILURES_GLOBAL=30
  HYPERFLO_TRUST_CF_CONNECTING_IP=1
  HYPERFLO_MAX_BODY_BYTES=65536, HYPERFLO_MAX_CHAT_BODY_BYTES=16777216

Generer un secret de session:
  python3 -c "import secrets; print(secrets.token_urlsafe(48))"

Deploiement
-----------
Le code est versionne avec git directement dans /opt/hyperflo-control.

1. Verifier (syntaxe, imports, demarrage, tests sur une instance de test
   isolee avec des identifiants factices). Ne pas redemarrer si ca echoue:
   ./check.sh
2. Installer les fichiers systeme et redemarrer (sauvegarde + retour arriere
   automatique si le service ne repond plus):
   sudo ./deploy/install.sh              (ajouter --sudoers pour la regle sudo)
3. Sinon, pour un changement de code seul:
   sudo systemctl restart hyperflo-control

Retour arriere du code: git log, puis git revert <commit>.
