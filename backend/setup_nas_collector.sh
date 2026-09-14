#!/bin/bash
# NAS collector setup — run ON THE SYNOLOGY (user lstorino, any dir).
# Usage:  PIG_TOKEN=<token> bash setup_nas_collector.sh
# Needs only outbound internet (pig333 scrape + push to VPS) — no port
# forwarding required.
set -euo pipefail

TOKEN="${PIG_TOKEN:?Set PIG_TOKEN first}"
DIR="$HOME/pigprices-collector"
BASE="https://raw.githubusercontent.com/lstorino/swinescarpping/master"

command -v python3 >/dev/null || { echo "ERROR: python3 not found — install the Python 3.9+ package from Package Center first"; exit 1; }

mkdir -p "$DIR/scraper"
curl -fsSL "$BASE/scraper/pig333.py"        -o "$DIR/scraper/pig333.py"
curl -fsSL "$BASE/backend/collect_and_push.py" -o "$DIR/collect_and_push.py"

cat > "$DIR/env.sh" <<EOF
export PIG_BACKEND=https://pig.maytek.co
export PIG_TOKEN=$TOKEN
EOF

cat > "$DIR/run.sh" <<'EOF'
#!/bin/bash
# 2x/day collector runner (Task Scheduler target)
source "$HOME/pigprices-collector/env.sh"
exec /usr/bin/python3 "$HOME/pigprices-collector/collect_and_push.py" >> "$HOME/pigprices-collector/last_run.log" 2>&1
EOF
chmod +x "$DIR/run.sh"

# resolve python3 once (DSM may put it elsewhere)
PY="$(command -v python3)"
sed -i "s|/usr/bin/python3|$PY|" "$DIR/run.sh"

echo "--- test run (real scrape + push) ---"
source "$DIR/env.sh" && "$PY" "$DIR/collect_and_push.py"
echo
echo "OK. Schedule in DSM: Control Panel > Task Scheduler > Create >"
echo "Scheduled Task > User-defined script, command:"
echo "  bash $DIR/run.sh"
echo "Schedule it twice daily (e.g. 07:10 and 19:10)."