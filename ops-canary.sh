#!/usr/bin/env bash

set -uo pipefail

NEW_VERSION="${1:?usage: canary <version> [city] [--bad]}"
CITY="${2:-vancouver}"
BAD="${3:-}"                       # pass --bad to simulate a broken build

case "$CITY" in
  vancouver) PORT=8001;; toronto) PORT=8002;; london) PORT=8003;;
  frankfurt) PORT=8004;; singapore) PORT=8005;;
  *) echo "unknown city: $CITY"; exit 2;;
esac
BASE="http://localhost:$PORT"
COMPOSE="docker compose -f docker-compose.yml"

deploy_city() {                    # args: version  degraded(true|false)
  local ver="$1" degraded="$2" ov; ov="$(mktemp)"
  cat > "$ov" <<EOF
services:
  $CITY:
    environment:
      VERSION: "$ver"
      DEGRADED_MODE: "$degraded"
EOF
  $COMPOSE -f "$ov" up -d --no-deps "$CITY" >/dev/null
  rm -f "$ov"
}


OLD_VERSION="$(curl -s "$BASE/health" | python3 -c 'import sys,json;print(json.load(sys.stdin)["version"])')"
echo "[canary] $CITY is on $OLD_VERSION -> canarying $NEW_VERSION"


[ "$BAD" = "--bad" ] && DEG=true || DEG=false
deploy_city "$NEW_VERSION" "$DEG"


printf "[canary] waiting for /ready"
READY=false
for i in $(seq 1 15); do
  [ "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/ready")" = "200" ] && { READY=true; break; }
  printf "."; sleep 1
done
echo
if [ "$READY" != true ]; then
  echo "[canary] never became ready -> rolling back to $OLD_VERSION"
  deploy_city "$OLD_VERSION" false; exit 1
fi


echo "[canary] sending 25 probe requests..."
for i in $(seq 1 25); do
  curl -s -o /dev/null -X POST "$BASE/infer" -H 'content-type: application/json' -d '{"prompt":"canary"}' &
done
wait


METRICS="$(curl -s "$BASE/metrics")"
HEALTH="$(curl -s -o /dev/null -w '%{http_code}' "$BASE/health")"
METRICS="$METRICS" HEALTH="$HEALTH" python3 - <<'PY'
import json, os, sys
m = json.loads(os.environ.get("METRICS") or "{}")
health_ok = os.environ.get("HEALTH") == "200"
err, p95 = m.get("error_rate", 1.0), m.get("p95_ms", 0.0)
ok = health_ok and err <= 0.05
print(f"[canary] health={'ok' if health_ok else 'BAD'} error_rate={err:.1%} p95_ms={p95:.0f} -> {'PASS' if ok else 'FAIL'}")
sys.exit(0 if ok else 1)
PY
GATE=$?


if [ "$GATE" -eq 0 ]; then
  echo "[canary] PASS — $CITY healthy on $NEW_VERSION. Safe to roll wider."
  exit 0
else
  echo "[canary] FAIL — rolling $CITY back to $OLD_VERSION. Other cities untouched."
  deploy_city "$OLD_VERSION" false; exit 1
fi
