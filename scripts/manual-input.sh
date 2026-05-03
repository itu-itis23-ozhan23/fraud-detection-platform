#!/usr/bin/env bash
# =============================================================================
# manual-input.sh — Submit a single transaction manually
# Usage: ./scripts/manual-input.sh <user_id> <amount> <location> [latitude] [longitude]
#
# Examples:
#   ./scripts/manual-input.sh user_001 500.00 Istanbul 41.0082 28.9784
#   ./scripts/manual-input.sh user_002 12500.00 Ankara
# =============================================================================

set -euo pipefail

API_URL="${API_URL:-http://localhost:8000}"

# ── Argument validation ───────────────────────────────────────────────────────
if [[ $# -lt 3 ]]; then
  echo "Usage: $0 <user_id> <amount> <location> [latitude] [longitude]"
  echo ""
  echo "Examples:"
  echo "  $0 user_001 500.00 Istanbul 41.0082 28.9784"
  echo "  $0 user_002 12500.00 Ankara"
  exit 1
fi

USER_ID="$1"
AMOUNT="$2"
LOCATION="$3"
LATITUDE="${4:-null}"
LONGITUDE="${5:-null}"

# Build JSON payload
if [[ "$LATITUDE" != "null" && "$LONGITUDE" != "null" ]]; then
  PAYLOAD=$(printf '{"user_id":"%s","amount":%s,"location":"%s","latitude":%s,"longitude":%s}' \
    "$USER_ID" "$AMOUNT" "$LOCATION" "$LATITUDE" "$LONGITUDE")
else
  PAYLOAD=$(printf '{"user_id":"%s","amount":%s,"location":"%s"}' \
    "$USER_ID" "$AMOUNT" "$LOCATION")
fi

echo "🔄 Submitting transaction..."
echo "   User:     $USER_ID"
echo "   Amount:   ₺$AMOUNT"
echo "   Location: $LOCATION"
echo ""

# Send to API
RESPONSE=$(curl -s -w "\n%{http_code}" \
  -X POST "$API_URL/api/v1/transactions/" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD")

HTTP_CODE=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | head -n -1)

if [[ "$HTTP_CODE" == "201" ]]; then
  TX_ID=$(echo "$BODY" | grep -o '"id":"[^"]*"' | cut -d'"' -f4)
  echo "✅ Transaction submitted successfully!"
  echo "   ID: $TX_ID"
  echo ""
  echo "📊 Raw response:"
  echo "$BODY" | python3 -m json.tool 2>/dev/null || echo "$BODY"
else
  echo "❌ Failed (HTTP $HTTP_CODE)"
  echo "$BODY"
  exit 1
fi
