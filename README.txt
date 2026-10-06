Hyperflo Control - backend Python decoupe

Fichiers:
- app.py             : creation de FastAPI et branchement des modules
- config.py          : configuration et variables d'environnement
- auth.py            : login, TOTP, sessions et anti brute-force
- system_monitor.py  : CPU, RAM, GPU, disques, reseau et liste Docker
- docker_api.py      : start/stop/restart/details/logs Docker
- ollama_api.py      : Ollama, streaming, thinking et recherche Web
- pages.py           : routes HTML
- requirements.txt   : dependances Python

Le service systemd peut continuer a lancer:
/opt/hyperflo-control/venv/bin/uvicorn app:app --host 127.0.0.1 --port 8080

Avant de remplacer le backend:
1. Sauvegarder l'ancien app.py.
2. Copier les .py dans /opt/hyperflo-control/.
3. Verifier les variables dans /etc/hyperflo-control.env.
4. Compiler: python -m py_compile app.py config.py auth.py system_monitor.py docker_api.py ollama_api.py pages.py
5. Redemarrer hyperflo-control seulement si la compilation ne retourne aucune erreur.
