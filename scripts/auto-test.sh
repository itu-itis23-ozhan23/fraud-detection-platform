#!/usr/bin/env bash
# =============================================================================
# auto-test.sh — Automated load + anomaly scenario generator
#
# Usage:
#   ./scripts/auto-test.sh [options]
#
# Options:
#   --duration=<seconds>        How long to run (default: 60)
#   --rate=<requests_per_second> Tx/s (default: 2)
#   --anomaly-chance=<0-100>    % chance of triggering an anomaly (default: 20)
#   --users=<count>             Number of distinct simulated users (default: 10)
#   --api-url=<url>             Base URL of API service (default: http://localhost:8000)
#
# Anomaly scenarios generated:
#   1. Velocity burst   — same user sends 7+ tx in ~10 seconds
#   2. Giant amount     — tx amount 5× user's recent average
#   3. Impossible travel — same user, Istanbul then Antalya within 2 minutes
# =============================================================================

set -euo pipefail

# ── Defaults ──────────────────────────────────────────────────────────────────
DURATION=60
RATE=2
ANOMALY_CHANCE=20
USER_COUNT=10
API_URL="${API_URL:-http://localhost:8000}"

# Parse options
for arg in "$@"; do
  case $arg in
    --duration=*)   DURATION="${arg#*=}" ;;
    --rate=*)       RATE="${arg#*=}" ;;
    --anomaly-chance=*) ANOMALY_CHANCE="${arg#*=}" ;;
    --users=*)      USER_COUNT="${arg#*=}" ;;
    --api-url=*)    API_URL="${arg#*=}" ;;
    -h|--help)
      sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
  esac
done

# ── City data ─────────────────────────────────────────────────────────────────
CITIES=("Istanbul:41.0082:28.9784" "Ankara:39.9334:32.8597" "Izmir:38.4192:27.1287"
        "Antalya:36.8969:30.7133" "Bursa:40.1826:29.0665" "Adana:37.0000:35.3213"
        "Konya:37.8746:32.4932" "Trabzon:41.0015:39.7178" "Samsun:41.2867:36.3300"
        "Gaziantep:37.0662:37.3833")

CITY_COUNT=${#CITIES[@]}

# ── Helpers ───────────────────────────────────────────────────────────────────
rand_int() { echo $(( RANDOM % ($2 - $1 + 1) + $1 )); }
rand_city() { echo "${CITIES[$(( RANDOM % CITY_COUNT ))]}"; }

parse_city() {
  local entry="$1"
  echo "${entry%%:*}"
}
parse_lat() {
  local entry="$1"
  echo "${entry#*:}" | cut -d: -f1
}
parse_lon() {
  local entry="$1"
  echo "${entry##*:}"
}

send_tx() {
  local user_id="$1" amount="$2" city="$3" lat="$4" lon="$5"
  local payload
  payload=$(printf '{"user_id":"%s","amount":%s,"location":"%s","latitude":%s,"longitude":%s}' \
    "$user_id" "$amount" "$city" "$lat" "$lon")
  curl -s -o /dev/null -w "%{http_code}" \
    -X POST "$API_URL/api/v1/transactions/" \
    -H "Content-Type: application/json" \
    -d "$payload"
}

counter_ok=0
counter_err=0
counter_anomaly=0

print_status() {
  echo -ne "\r  ✅ OK: $counter_ok  ❌ Errors: $counter_err  🚨 Anomalies triggered: $counter_anomaly   "
}

# ── Anomaly scenarios ─────────────────────────────────────────────────────────

scenario_velocity() {
  local user_id="$1"
  local city_entry; city_entry=$(rand_city)
  local city; city=$(parse_city "$city_entry")
  local lat;  lat=$(parse_lat "$city_entry")
  local lon;  lon=$(parse_lon "$city_entry")
  local amount; amount=$(rand_int 50 300)

  echo ""
  echo "  🚨 [ANOMALY] Velocity burst for $user_id — sending 8 rapid transactions"
  for i in $(seq 1 8); do
    code=$(send_tx "$user_id" "$amount" "$city" "$lat" "$lon")
    [[ "$code" == "201" ]] && (( counter_ok++ )) || (( counter_err++ ))
    sleep 0.5
  done
  (( counter_anomaly++ ))
}

scenario_giant_amount() {
  local user_id="$1"
  local city_entry; city_entry=$(rand_city)
  local city; city=$(parse_city "$city_entry")
  local lat;  lat=$(parse_lat "$city_entry")
  local lon;  lon=$(parse_lon "$city_entry")

  # Seed with small amounts first
  echo ""
  echo "  🚨 [ANOMALY] Giant amount for $user_id — seeding then spiking"
  for amount in 100 120 90 110 105; do
    code=$(send_tx "$user_id" "$amount" "$city" "$lat" "$lon")
    [[ "$code" == "201" ]] && (( counter_ok++ )) || (( counter_err++ ))
    sleep 0.3
  done
  # Spike at 5× average (~520)
  spike=$(rand_int 500 800)
  code=$(send_tx "$user_id" "$spike" "$city" "$lat" "$lon")
  [[ "$code" == "201" ]] && (( counter_ok++ )) || (( counter_err++ ))
  (( counter_anomaly++ ))
}

scenario_impossible_travel() {
  local user_id="$1"
  echo ""
  echo "  🚨 [ANOMALY] Impossible travel for $user_id — Istanbul → Antalya (2 min apart)"

  code=$(send_tx "$user_id" "$(rand_int 100 400)" "Istanbul" "41.0082" "28.9784")
  [[ "$code" == "201" ]] && (( counter_ok++ )) || (( counter_err++ ))
  sleep 1
  code=$(send_tx "$user_id" "$(rand_int 100 400)" "Antalya" "36.8969" "30.7133")
  [[ "$code" == "201" ]] && (( counter_ok++ )) || (( counter_err++ ))
  (( counter_anomaly++ ))
}

# ── Main loop ─────────────────────────────────────────────────────────────────
SLEEP_MS=$(echo "scale=3; 1 / $RATE" | bc)
END_TIME=$(( $(date +%s) + DURATION ))

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║        🚀 Fraud Detection Auto-Test Script           ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
echo "  API URL   : $API_URL"
echo "  Duration  : ${DURATION}s"
echo "  Rate      : ${RATE} req/s"
echo "  Anomaly % : ${ANOMALY_CHANCE}%"
echo "  Users     : $USER_COUNT"
echo ""
echo "  Starting in 2 seconds..."
sleep 2
echo ""

while [[ $(date +%s) -lt $END_TIME ]]; do
  USER_ID="user_$(printf '%03d' $(rand_int 1 $USER_COUNT))"
  ROLL=$(rand_int 1 100)

  if [[ $ROLL -le $ANOMALY_CHANCE ]]; then
    SCENARIO=$(rand_int 1 3)
    case $SCENARIO in
      1) scenario_velocity "$USER_ID" ;;
      2) scenario_giant_amount "$USER_ID" ;;
      3) scenario_impossible_travel "$USER_ID" ;;
    esac
  else
    CITY_ENTRY=$(rand_city)
    CITY=$(parse_city "$CITY_ENTRY")
    LAT=$(parse_lat "$CITY_ENTRY")
    LON=$(parse_lon "$CITY_ENTRY")
    AMOUNT="$(rand_int 50 500).$(rand_int 0 99)"

    CODE=$(send_tx "$USER_ID" "$AMOUNT" "$CITY" "$LAT" "$LON")
    if [[ "$CODE" == "201" ]]; then
      (( counter_ok++ ))
    else
      (( counter_err++ ))
    fi
  fi

  print_status
  sleep "$SLEEP_MS" 2>/dev/null || sleep 1
done

echo ""
echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║                    ✅ Test Complete                   ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
echo "  Total OK        : $counter_ok"
echo "  Total Errors    : $counter_err"
echo "  Anomalies fired : $counter_anomaly"
echo ""
