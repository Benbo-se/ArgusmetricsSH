#!/usr/bin/env bash
# The one step on the server that needs root, run once:
#
#   ssh -t reda@<server> sudo /opt/argusmetrics/deploy/install-host-access.sh
#
# It installs deploy/argus-host-nginx as a root-owned command and a sudoers
# line letting the deploy user run exactly that command, with no arguments
# and no password. Then it runs it once. After this, every deploy keeps the
# host vhost in step with deploy/nginx/argusmetrics.conf by itself.
#
# Run it again only if deploy/argus-host-nginx itself changes; the deploy
# warns when the installed copy and the repository disagree. Idempotent.
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "run with sudo" >&2; exit 1; }

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USER_NAME="${SUDO_USER:-}"
[ -n "$USER_NAME" ] && [ "$USER_NAME" != root ] \
    || { echo "run through sudo as the deploy user, not as root directly" >&2; exit 1; }

install -m 0755 -o root -g root "$DIR/argus-host-nginx" /usr/local/sbin/argus-host-nginx
echo "installed /usr/local/sbin/argus-host-nginx"

# The trailing "" means no arguments are allowed. Without it, sudo would
# accept any arguments, including --check with a path of the caller's choice.
RULE="$USER_NAME ALL=(root) NOPASSWD: /usr/local/sbin/argus-host-nginx \"\""
TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT
printf '# Installed by ArgusmetricsSH deploy/install-host-access.sh\n%s\n' "$RULE" > "$TMP"
visudo -cf "$TMP" >/dev/null || { echo "sudoers line did not validate; nothing installed" >&2; exit 1; }
install -m 0440 -o root -g root "$TMP" /etc/sudoers.d/argusmetrics
echo "installed /etc/sudoers.d/argusmetrics: $RULE"

/usr/local/sbin/argus-host-nginx
