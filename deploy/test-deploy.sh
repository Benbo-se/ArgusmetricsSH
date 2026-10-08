#!/usr/bin/env bash
# Runs the deploy workflow's server script through its scenarios, against a
# real git repository and stubbed docker, curl and sleep (#111).
#
# The script only ever ran against production, so the first time a rollback
# was exercised was the first time it was needed. These are the cases it has
# to get right, and the property that matters in each: the images and the
# configuration (compose file, nginx config, everything in the checkout) come
# from the same commit at every `compose up`.
#
#   bash deploy/test-deploy.sh      # needs python3 with PyYAML, and git
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
mkdir -p "$T/bin" "$T/home"

python3 - "$ROOT/.github/workflows/deploy.yml" "$T/server.sh" <<'PY'
import sys, yaml
steps = yaml.safe_load(open(sys.argv[1]))["jobs"]["deploy"]["steps"]
script = next(s["with"]["script"] for s in steps if s.get("uses", "").startswith("appleboy/ssh-action"))
open(sys.argv[2], "w").write(script)
PY

# docker: records every call; `compose up` records the tag it ran and whether
# the checkout was at the same commit at that moment.
cat > "$T/bin/docker" <<'EOF'
#!/usr/bin/env bash
case "$1" in
  inspect) echo "ghcr.io/benbo-se/argusmetrics-backend:$(cat "$T/running")" ;;
  compose)
    shift 3
    case "$1" in
      pull) [ -n "${FAIL_PULL:-}" ] && exit 1; true ;;
      up) echo "$ARGUS_TAG" > "$T/running"
          if [ "$(git -C "$T/work" rev-parse HEAD)" = "$ARGUS_TAG" ]; then echo match; else echo MISMATCH; fi >> "$T/ups" ;;
      exec) echo "dump" ;;
    esac ;;
esac
true
EOF
cat > "$T/bin/curl" <<'EOF'
#!/usr/bin/env bash
if [ -n "${BROKEN:-}" ] && [ "$(cat "$T/running")" = "$BROKEN" ]; then echo '{"status":"unhealthy"}'; else echo '{"status":"healthy"}'; fi
EOF
printf '#!/usr/bin/env bash\ntrue\n' > "$T/bin/sleep"
printf '#!/usr/bin/env bash\nexit 1\n' > "$T/bin/sudo"
chmod +x "$T/bin/"*

# Three commits on main, A < B < C, each with a different compose file.
# Production runs B: its image and its checkout.
setup() {
  rm -rf "$T/origin" "$T/work"
  git init -q --bare -b main "$T/origin"
  git clone -q "$T/origin" "$T/work" 2>/dev/null
  (
    cd "$T/work"
    git config user.email t@example.com; git config user.name test
    mkdir -p docker; printf '.env\n' > .gitignore
    for v in A B C; do echo "$v" > docker/docker-compose.prod.yml; git add -A; git commit -qm "$v"; done
    git push -q origin main
  )
  A=$(git -C "$T/work" rev-parse HEAD~2); B=$(git -C "$T/work" rev-parse HEAD~1); C=$(git -C "$T/work" rev-parse HEAD)
  git -C "$T/work" reset -q --hard "$B"
  printf 'BASE_URL=https://example.test\nARGUS_TAG=%s\n' "$B" > "$T/work/docker/.env"
  echo "$B" > "$T/running"; : > "$T/ups"
}

deploy() {
  sed "s#cd /opt/argusmetrics#cd $T/work#" "$T/server.sh" > "$T/run.sh"
  set +e
  env PATH="$T/bin:$PATH" HOME="$T/home" T="$T" "$@" bash "$T/run.sh" > "$T/out" 2>&1
  STATUS=$?
  set -e
}

FAILED=0
expect() {  # description, condition
  if eval "$2"; then echo "  ok: $1"; else echo "  FAIL: $1"; FAILED=1; tail -5 "$T/out" | sed 's/^/    /'; fi
}
at() { git -C "$T/work" rev-parse HEAD; }
env_tag() { grep ARGUS_TAG "$T/work/docker/.env" | cut -d= -f2; }
consistent() { ! grep -q MISMATCH "$T/ups"; }

echo "Automatic deploy of main's head"
setup; deploy DEPLOY_TAG="$C" DEPLOY_KIND=auto
expect "succeeds" '[ $STATUS -eq 0 ]'
expect "runs C, configured from C, recorded" '[ "$(cat $T/running)" = "$C" ] && [ "$(at)" = "$C" ] && [ "$(env_tag)" = "$C" ]'
expect "images and configuration match at every up" consistent

echo "Automatic deploy that main has already passed (queued behind a newer one)"
setup; deploy DEPLOY_TAG="$A" DEPLOY_KIND=auto
expect "skips without touching anything" '[ $STATUS -eq 0 ] && [ ! -s $T/ups ] && [ "$(at)" = "$B" ]'

echo "Manual deploy of an older commit (rollback by hand)"
setup; deploy DEPLOY_TAG="$A" DEPLOY_KIND=manual
expect "runs A, configured from A" '[ $STATUS -eq 0 ] && [ "$(cat $T/running)" = "$A" ] && [ "$(at)" = "$A" ]'
expect "images and configuration match at every up" consistent

echo "Deploy that fails its health check"
setup; deploy DEPLOY_TAG="$C" DEPLOY_KIND=auto BROKEN="$C"
expect "fails" '[ $STATUS -ne 0 ]'
expect "rolls back to B, configured from B, recorded as B" '[ "$(cat $T/running)" = "$B" ] && [ "$(at)" = "$B" ] && [ "$(env_tag)" = "$B" ]'
expect "images and configuration match at every up, the rollback's too" consistent

echo "Deploy whose images cannot be pulled"
setup; deploy DEPLOY_TAG="$C" DEPLOY_KIND=auto FAIL_PULL=1
expect "fails with nothing changed" '[ $STATUS -ne 0 ] && [ ! -s $T/ups ] && [ "$(at)" = "$B" ] && [ "$(env_tag)" = "$B" ]'

echo "Deploy of a commit that does not exist"
setup; deploy DEPLOY_TAG="$(printf 'f%.0s' {1..40})" DEPLOY_KIND=manual
expect "fails with nothing changed" '[ $STATUS -ne 0 ] && [ ! -s $T/ups ] && [ "$(at)" = "$B" ]'

[ "$FAILED" -eq 0 ] && echo "Deploy script: all scenarios hold." || { echo "Deploy script: scenarios failed."; exit 1; }
