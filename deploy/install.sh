#!/bin/bash
# Installe les fichiers systeme de Hyperflo Control puis redemarre le service.
#
#   sudo ./deploy/install.sh             scripts sudo + unite systemd
#   sudo ./deploy/install.sh --sudoers   idem + remplace /etc/sudoers.d/hyperflo-control
#
# Les fichiers remplaces sont sauvegardes dans /root/hyperflo-control-backup-*.
# Si le service ne repond pas apres redemarrage, ils sont restaures.

set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
SERVICE=hyperflo-control
UNIT=/etc/systemd/system/$SERVICE.service
SUDOERS=/etc/sudoers.d/$SERVICE
SBIN_FILES=(hyperflo-docker-action hyperflo-docker-info hyperflo-docker-list hyperflo-docker-stats
    hyperflo-minecraft-action hyperflo-service-action hyperflo-service-logs hyperflo-power)

if [ "$(id -u)" -ne 0 ]; then
    echo "A lancer avec sudo." >&2
    exit 1
fi

INSTALL_SUDOERS=0
if [ "${1:-}" = "--sudoers" ]; then
    INSTALL_SUDOERS=1
fi

BACKUP="/root/$SERVICE-backup-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP"
chmod 700 "$BACKUP"
cp -a "$UNIT" "$BACKUP/"
for name in "${SBIN_FILES[@]}"; do
    # Un nouveau script n'existe pas encore: rien a sauvegarder.
    if [ -f "/usr/local/sbin/$name" ]; then
        cp -a "/usr/local/sbin/$name" "$BACKUP/"
    fi
done
if [ -f "$SUDOERS" ]; then
    cp -a "$SUDOERS" "$BACKUP/"
fi
echo "Sauvegarde: $BACKUP"

restore() {
    echo "ECHEC: restauration des fichiers systeme depuis $BACKUP" >&2
    cp -a "$BACKUP/$SERVICE.service" "$UNIT"
    for name in "${SBIN_FILES[@]}"; do
        if [ -f "$BACKUP/$name" ]; then
            cp -a "$BACKUP/$name" "/usr/local/sbin/$name"
        else
            rm -f "/usr/local/sbin/$name"
        fi
    done
    if [ -f "$BACKUP/$SERVICE" ]; then
        cp -a "$BACKUP/$SERVICE" "$SUDOERS"
    fi
    systemctl daemon-reload
    systemctl restart "$SERVICE" || true
    echo "Si le probleme vient du code Python: cd /opt/$SERVICE && git log" >&2
    exit 1
}

# 1. Scripts appeles via sudo: root uniquement, non modifiables par le service.
for name in "${SBIN_FILES[@]}"; do
    install -o root -g root -m 0755 "$SRC/sbin/$name" "/usr/local/sbin/$name"
done

# 2. Regle sudo (optionnelle), validee avant installation.
if [ "$INSTALL_SUDOERS" -eq 1 ]; then
    visudo -cf "$SRC/sudoers/$SERVICE"
    install -o root -g root -m 0440 "$SRC/sudoers/$SERVICE" "$SUDOERS"
    visudo -c >/dev/null || restore
fi

# 3. Unite systemd.
install -o root -g root -m 0644 "$SRC/systemd/$SERVICE.service" "$UNIT"
systemctl daemon-reload
systemctl restart "$SERVICE"

# 4. Verifications.
ok=0
for _ in $(seq 1 15); do
    # -s sans -S: pas de message d'erreur pendant que le service demarre.
    if curl -fs -o /dev/null http://127.0.0.1:8080/login; then
        ok=1
        break
    fi
    sleep 1
done

if [ "$ok" -ne 1 ]; then
    journalctl -u "$SERVICE" -n 30 --no-pager >&2 || true
    restore
fi

# Lance une commande comme le service: meme utilisateur, meme durcissement.
sandboxed() {
    local args=(-p User=hyperflo -p Group=hyperflo)
    local prop
    while read -r prop; do
        args+=(-p "$prop")
    done < <(sed -n '/^# --- Durcissement ---/,/^UMask=/p' "$UNIT" | grep -E '^[A-Za-z]+=')
    systemd-run --wait --pipe --quiet "${args[@]}" "$@"
}

if ! sandboxed /usr/bin/sudo -n /usr/local/sbin/hyperflo-docker-list >/dev/null; then
    echo "hyperflo ne peut pas lancer hyperflo-docker-list via sudo dans le service." >&2
    restore
fi

if ! sandboxed /usr/bin/sudo -n /usr/local/sbin/hyperflo-docker-stats >/dev/null; then
    echo "Attention: hyperflo-docker-stats refuse via sudo (regle sudoers a jour?" >&2
    echo "  relancer avec --sudoers). CPU/RAM des conteneurs indisponibles." >&2
fi

# Le script Minecraft pilote playit.service via systemctl: verifie que
# systemd repond depuis le bac a sable du service (lecture seule).
if ! sandboxed /usr/bin/systemctl show -p ActiveState playit.service >/dev/null; then
    echo "Attention: systemctl ne repond pas depuis le service (Playit)." >&2
fi

if ! sandboxed /usr/bin/sudo -n /usr/local/sbin/hyperflo-service-logs hyperflo 1 >/dev/null; then
    echo "Attention: hyperflo-service-logs refuse via sudo (relancer avec --sudoers)." >&2
fi

if [ -x /usr/bin/nvidia-smi ] && ! sandboxed /usr/bin/nvidia-smi -L >/dev/null; then
    echo "Attention: nvidia-smi echoue dans le service (GPU absent du dashboard)." >&2
fi

echo "OK: $SERVICE redemarre et operationnel."
systemctl --no-pager --lines=0 status "$SERVICE"
