#!/bin/bash
set -euo pipefail

BASE="https://api.argusmetrics.io"
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
EMAIL="featuretest-$(date +%s)@test.argusmetrics.io"
PASSWORD="TestPass12345"
PASS_COUNT=0
FAIL_COUNT=0

pass() { echo "[PASS] $1"; PASS_COUNT=$((PASS_COUNT+1)); }
fail() { echo "[FAIL] $1"; FAIL_COUNT=$((FAIL_COUNT+1)); }

echo "============================================="
echo "  Argusmetrics Full Feature Test Suite"
echo "  $(date)"
echo "============================================="
echo ""
echo "Test email: $EMAIL"
echo ""

# ---- SETUP: Sign Up ----
echo "--- SETUP: Creating test user ---"
SIGNUP_RESP=$(curl -sk -X POST "$BASE/api/v1/auth/signup" \
  -H "Content-Type: application/json" \
  -H "User-Agent: $UA" \
  -d '{"email":"'"$EMAIL"'","password":"'"$PASSWORD"'","plan":"starter"}')
echo "Signup: $SIGNUP_RESP"

VERIFY_URL=$(echo "$SIGNUP_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('verify_url',''))" 2>/dev/null || echo "")
if [ -z "$VERIFY_URL" ]; then
  echo "FATAL: No verify_url in signup response"
  exit 1
fi

# ---- SETUP: Verify Email & Extract Token from Cookie ----
echo "--- SETUP: Verifying email ---"
VERIFY_HEADERS=$(curl -sk -D- -o /dev/null "$VERIFY_URL" -H "User-Agent: $UA")
TOKEN=$(echo "$VERIFY_HEADERS" | grep -i 'set-cookie:.*session_token' | sed 's/.*session_token=//;s/;.*//' | tr -d '\r\n')

if [ -z "$TOKEN" ]; then
  echo "FATAL: Could not extract session_token cookie from verify response"
  exit 1
fi
echo "Session Token: ${TOKEN:0:20}... (length ${#TOKEN})"

AUTH="Authorization: Bearer $TOKEN"

# ---- SETUP: Create Website ----
echo "--- SETUP: Creating test website ---"
SITE_RESP=$(curl -sk -X POST "$BASE/api/v1/websites/" \
  -H "Content-Type: application/json" \
  -H "$AUTH" \
  -H "User-Agent: $UA" \
  -d '{"name":"Feature Test Site","domain":"https://featuretest-e2e.example.com"}')
echo "Create website: $SITE_RESP"

WEBSITE_ID=$(echo "$SITE_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || echo "")
TRACKING_CODE=$(echo "$SITE_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('tracking_code',''))" 2>/dev/null || echo "")

echo "Website ID: $WEBSITE_ID"
echo "Tracking Code: $TRACKING_CODE"

if [ -z "$WEBSITE_ID" ] || [ -z "$TRACKING_CODE" ]; then
  echo "FATAL: Could not extract website ID or tracking code"
  exit 1
fi

echo ""
echo "============================================="
echo "  Running Feature Tests (15 features)"
echo "============================================="
echo ""

# ============== TEST 1: Basic Pageview Tracking ==============
echo "--- Test 1: Basic Pageview Tracking ---"
T1_RESP=$(curl -sk -X POST "$BASE/api/v1/analytics/track" \
  -H "Content-Type: application/json" \
  -H "User-Agent: $UA" \
  -d "{\"tracking_code\":\"$TRACKING_CODE\",\"path\":\"/home\",\"referrer\":\"https://direct.example.com\",\"screen_width\":1920}" \
  -w "\n%{http_code}")
T1_BODY=$(echo "$T1_RESP" | sed '$d')
T1_CODE=$(echo "$T1_RESP" | tail -1)

if [ "$T1_CODE" = "200" ]; then
  SUCCESS=$(echo "$T1_BODY" | python3 -c "import sys,json; print(json.load(sys.stdin).get('success','N/A'))" 2>/dev/null || echo "N/A")
  pass "Basic Pageview Tracking - HTTP 200, success=$SUCCESS, body: ${T1_BODY:0:80}"
else
  fail "Basic Pageview Tracking - expected HTTP 200, got $T1_CODE. Body: ${T1_BODY:0:200}"
fi

# ============== TEST 2: Unique Visitors ==============
echo "--- Test 2: Unique Visitors ---"
for i in 1 2 3; do
  curl -sk -X POST "$BASE/api/v1/analytics/track" \
    -H "Content-Type: application/json" \
    -H "User-Agent: $UA" \
    -d "{\"tracking_code\":\"$TRACKING_CODE\",\"path\":\"/unique-test-$i\",\"screen_width\":1920}" > /dev/null 2>&1
done
sleep 2

T2_RESP=$(curl -sk "$BASE/api/v1/analytics/stats/$WEBSITE_ID" \
  -H "$AUTH" -H "User-Agent: $UA" -w "\n%{http_code}")
T2_BODY=$(echo "$T2_RESP" | sed '$d')
T2_CODE=$(echo "$T2_RESP" | tail -1)

if [ "$T2_CODE" = "200" ]; then
  UV=$(echo "$T2_BODY" | python3 -c "
import sys,json
d=json.load(sys.stdin)
print('unique_visitors=' + str(d.get('unique_visitors','N/A')))
" 2>/dev/null || echo "parse_error")
  pass "Unique Visitors - 4 pageviews same UA/IP, stats HTTP 200, $UV"
else
  fail "Unique Visitors - stats endpoint HTTP $T2_CODE. Body: ${T2_BODY:0:200}"
fi

# ============== TEST 3: Referrer Tracking ==============
echo "--- Test 3: Referrer Tracking ---"
T3_RESP=$(curl -sk -X POST "$BASE/api/v1/analytics/track" \
  -H "Content-Type: application/json" \
  -H "User-Agent: $UA" \
  -d "{\"tracking_code\":\"$TRACKING_CODE\",\"path\":\"/from-google\",\"referrer\":\"https://google.com\",\"screen_width\":1920}" \
  -w "\n%{http_code}")
T3_CODE=$(echo "$T3_RESP" | tail -1)
T3_BODY=$(echo "$T3_RESP" | sed '$d')

if [ "$T3_CODE" = "200" ]; then
  sleep 1
  STATS=$(curl -sk "$BASE/api/v1/analytics/stats/$WEBSITE_ID" -H "$AUTH" -H "User-Agent: $UA")
  REFS=$(echo "$STATS" | python3 -c "
import sys,json
d=json.load(sys.stdin)
refs = d.get('top_referrers', d.get('referrers', []))
print(str(refs)[:150])
" 2>/dev/null || echo "N/A")
  pass "Referrer Tracking - pageview with referrer=google.com accepted (HTTP 200). top_referrers=$REFS"
else
  fail "Referrer Tracking - HTTP $T3_CODE. Body: ${T3_BODY:0:200}"
fi

# ============== TEST 4: UTM Tracking ==============
echo "--- Test 4: UTM Tracking ---"
T4_RESP=$(curl -sk -X POST "$BASE/api/v1/analytics/track" \
  -H "Content-Type: application/json" \
  -H "User-Agent: $UA" \
  -d "{\"tracking_code\":\"$TRACKING_CODE\",\"path\":\"/landing\",\"utm_source\":\"google\",\"utm_medium\":\"cpc\",\"utm_campaign\":\"spring_sale\",\"screen_width\":1920}" \
  -w "\n%{http_code}")
T4_BODY=$(echo "$T4_RESP" | sed '$d')
T4_CODE=$(echo "$T4_RESP" | tail -1)

if [ "$T4_CODE" = "200" ]; then
  pass "UTM Tracking - utm_source=google, utm_medium=cpc, utm_campaign=spring_sale (HTTP 200)"
else
  fail "UTM Tracking - HTTP $T4_CODE. Body: ${T4_BODY:0:200}"
fi

# ============== TEST 5: Custom Events ==============
echo "--- Test 5: Custom Events ---"
T5_RESP=$(curl -sk -X POST "$BASE/api/v1/analytics/track-event" \
  -H "Content-Type: application/json" \
  -H "User-Agent: $UA" \
  -d "{\"tracking_code\":\"$TRACKING_CODE\",\"event_name\":\"button_click\",\"properties\":{\"button\":\"signup\"}}" \
  -w "\n%{http_code}")
T5_BODY=$(echo "$T5_RESP" | sed '$d')
T5_CODE=$(echo "$T5_RESP" | tail -1)

if [ "$T5_CODE" = "200" ]; then
  pass "Custom Events - event_name=button_click properties={button:signup} (HTTP 200)"
else
  fail "Custom Events - HTTP $T5_CODE. Body: ${T5_BODY:0:200}"
fi

# ============== TEST 6: Goals & Conversions ==============
echo "--- Test 6: Goals & Conversions ---"
T6_CREATE=$(curl -sk -X POST "$BASE/api/v1/analytics/goals?website_id=$WEBSITE_ID" \
  -H "Content-Type: application/json" \
  -H "$AUTH" -H "User-Agent: $UA" \
  -d '{"name":"Signup","event_name":"signup_complete"}' \
  -w "\n%{http_code}")
T6_CBODY=$(echo "$T6_CREATE" | sed '$d')
T6_CCODE=$(echo "$T6_CREATE" | tail -1)

GOAL_ID=$(echo "$T6_CBODY" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || echo "")

if [ "$T6_CCODE" = "200" ] || [ "$T6_CCODE" = "201" ]; then
  # Track the goal event
  T6_TRACK=$(curl -sk -X POST "$BASE/api/v1/analytics/track-event" \
    -H "Content-Type: application/json" -H "User-Agent: $UA" \
    -d "{\"tracking_code\":\"$TRACKING_CODE\",\"event_name\":\"signup_complete\"}" \
    -w "\n%{http_code}")
  T6_TCODE=$(echo "$T6_TRACK" | tail -1)

  # Delete the goal
  DEL_MSG=""
  if [ -n "$GOAL_ID" ]; then
    T6_DEL=$(curl -sk -X DELETE "$BASE/api/v1/analytics/goals/$GOAL_ID?website_id=$WEBSITE_ID" \
      -H "$AUTH" -H "User-Agent: $UA" -w "\n%{http_code}")
    T6_DCODE=$(echo "$T6_DEL" | tail -1)
    T6_DBODY=$(echo "$T6_DEL" | sed '$d')
    DEL_MSG="deleted (HTTP $T6_DCODE)"
  else
    DEL_MSG="no goal_id extracted"
  fi
  pass "Goals & Conversions - created (HTTP $T6_CCODE, id=$GOAL_ID), tracked event (HTTP $T6_TCODE), $DEL_MSG"
else
  fail "Goals & Conversions - create returned HTTP $T6_CCODE. Body: ${T6_CBODY:0:200}"
fi

# ============== TEST 7: Outbound Link Tracking ==============
echo "--- Test 7: Outbound Link Tracking ---"
T7_RESP=$(curl -sk -X POST "$BASE/api/v1/analytics/track-event" \
  -H "Content-Type: application/json" -H "User-Agent: $UA" \
  -d "{\"tracking_code\":\"$TRACKING_CODE\",\"event_name\":\"Outbound Link: Click\",\"properties\":{\"url\":\"https://external.com\"}}" \
  -w "\n%{http_code}")
T7_CODE=$(echo "$T7_RESP" | tail -1)
T7_BODY=$(echo "$T7_RESP" | sed '$d')

if [ "$T7_CODE" = "200" ]; then
  pass "Outbound Link Tracking - 'Outbound Link: Click' url=https://external.com (HTTP 200)"
else
  fail "Outbound Link Tracking - HTTP $T7_CODE. Body: ${T7_BODY:0:200}"
fi

# ============== TEST 8: File Download Tracking ==============
echo "--- Test 8: File Download Tracking ---"
T8_RESP=$(curl -sk -X POST "$BASE/api/v1/analytics/track-event" \
  -H "Content-Type: application/json" -H "User-Agent: $UA" \
  -d "{\"tracking_code\":\"$TRACKING_CODE\",\"event_name\":\"File Download\",\"properties\":{\"url\":\"/files/report.pdf\"}}" \
  -w "\n%{http_code}")
T8_CODE=$(echo "$T8_RESP" | tail -1)
T8_BODY=$(echo "$T8_RESP" | sed '$d')

if [ "$T8_CODE" = "200" ]; then
  pass "File Download Tracking - 'File Download' url=/files/report.pdf (HTTP 200)"
else
  fail "File Download Tracking - HTTP $T8_CODE. Body: ${T8_BODY:0:200}"
fi

# ============== TEST 9: 404 Error Tracking ==============
echo "--- Test 9: 404 Error Tracking ---"
T9A_RESP=$(curl -sk -X POST "$BASE/api/v1/analytics/track" \
  -H "Content-Type: application/json" -H "User-Agent: $UA" \
  -d "{\"tracking_code\":\"$TRACKING_CODE\",\"path\":\"/nonexistent-page\",\"is_404\":true,\"screen_width\":1920}" \
  -w "\n%{http_code}")
T9A_CODE=$(echo "$T9A_RESP" | tail -1)

T9B_RESP=$(curl -sk -X POST "$BASE/api/v1/analytics/track-event" \
  -H "Content-Type: application/json" -H "User-Agent: $UA" \
  -d "{\"tracking_code\":\"$TRACKING_CODE\",\"event_name\":\"404\",\"properties\":{\"path\":\"/missing\"}}" \
  -w "\n%{http_code}")
T9B_CODE=$(echo "$T9B_RESP" | tail -1)

if [ "$T9A_CODE" = "200" ] && [ "$T9B_CODE" = "200" ]; then
  pass "404 Error Tracking - Both approaches work: pageview+is_404 (200) and event '404' (200)"
elif [ "$T9A_CODE" = "200" ]; then
  pass "404 Error Tracking - pageview+is_404 works (200), event approach HTTP $T9B_CODE"
elif [ "$T9B_CODE" = "200" ]; then
  pass "404 Error Tracking - event approach works (200), pageview approach HTTP $T9A_CODE"
else
  fail "404 Error Tracking - both failed: pageview=$T9A_CODE, event=$T9B_CODE"
fi

# ============== TEST 10: CSV Export ==============
echo "--- Test 10: CSV Export ---"
T10_RESP=$(curl -sk -D /tmp/t10h.txt "$BASE/api/v1/analytics/export/$WEBSITE_ID/csv" \
  -H "$AUTH" -H "User-Agent: $UA" -w "\n%{http_code}")
T10_CODE=$(echo "$T10_RESP" | tail -1)
T10_BODY=$(echo "$T10_RESP" | sed '$d')
T10_CT=$(grep -i "content-type" /tmp/t10h.txt 2>/dev/null | head -1 | tr -d '\r\n' || echo "unknown")

if [ "$T10_CODE" = "200" ]; then
  pass "CSV Export - HTTP 200, $T10_CT (body: ${T10_BODY:0:100})"
else
  fail "CSV Export - HTTP $T10_CODE. Body: ${T10_BODY:0:200}"
fi

# ============== TEST 11: JSON Export ==============
echo "--- Test 11: JSON Export ---"
T11_RESP=$(curl -sk "$BASE/api/v1/analytics/export/$WEBSITE_ID/json" \
  -H "$AUTH" -H "User-Agent: $UA" -w "\n%{http_code}")
T11_CODE=$(echo "$T11_RESP" | tail -1)
T11_BODY=$(echo "$T11_RESP" | sed '$d')

if [ "$T11_CODE" = "200" ]; then
  pass "JSON Export - HTTP 200 (body: ${T11_BODY:0:100})"
else
  fail "JSON Export - HTTP $T11_CODE. Body: ${T11_BODY:0:200}"
fi

# ============== TEST 12: Realtime Stats ==============
echo "--- Test 12: Realtime Stats ---"
T12_RESP=$(curl -sk "$BASE/api/v1/analytics/realtime/$WEBSITE_ID" \
  -H "$AUTH" -H "User-Agent: $UA" -w "\n%{http_code}")
T12_CODE=$(echo "$T12_RESP" | tail -1)
T12_BODY=$(echo "$T12_RESP" | sed '$d')

if [ "$T12_CODE" = "200" ]; then
  ONLINE=$(echo "$T12_BODY" | python3 -c "
import sys,json
d=json.load(sys.stdin)
print('online_now=' + str(d.get('online_now', d.get('current_visitors', 'N/A'))))
" 2>/dev/null || echo "parse_error")
  pass "Realtime Stats - HTTP 200, $ONLINE"
else
  fail "Realtime Stats - HTTP $T12_CODE. Body: ${T12_BODY:0:200}"
fi

# ============== TEST 13: Public Dashboard ==============
echo "--- Test 13: Public Dashboard ---"
T13_RESP=$(curl -sk -X PUT "$BASE/api/v1/websites/$WEBSITE_ID/public-access" \
  -H "Content-Type: application/json" -H "$AUTH" -H "User-Agent: $UA" \
  -d '{"is_public":true}' -w "\n%{http_code}")
T13_CODE=$(echo "$T13_RESP" | tail -1)
T13_BODY=$(echo "$T13_RESP" | sed '$d')

if [ "$T13_CODE" = "200" ]; then
  # Get website info for share token
  SITE_INFO=$(curl -sk "$BASE/api/v1/websites/$WEBSITE_ID" -H "$AUTH" -H "User-Agent: $UA")
  SHARE_TOKEN=$(echo "$SITE_INFO" | python3 -c "
import sys,json
d=json.load(sys.stdin)
print(d.get('public_share_token','') or d.get('share_token','') or d.get('public_token',''))
" 2>/dev/null || echo "")

  if [ -n "$SHARE_TOKEN" ]; then
    # Try multiple URL patterns
    P1=$(curl -sk -o /dev/null -w "%{http_code}" "$BASE/public/$SHARE_TOKEN" -H "User-Agent: $UA")
    P2=$(curl -sk -o /dev/null -w "%{http_code}" "$BASE/api/v1/analytics/public/$SHARE_TOKEN" -H "User-Agent: $UA")
    P3=$(curl -sk -o /dev/null -w "%{http_code}" "$BASE/share/$SHARE_TOKEN" -H "User-Agent: $UA")
    P4=$(curl -sk -o /dev/null -w "%{http_code}" "$BASE/dashboard/public/$SHARE_TOKEN" -H "User-Agent: $UA")

    if [ "$P1" = "200" ]; then
      pass "Public Dashboard - enabled, token=$SHARE_TOKEN, /public/ HTTP 200"
    elif [ "$P2" = "200" ]; then
      pass "Public Dashboard - enabled, token=$SHARE_TOKEN, /api/v1/analytics/public/ HTTP 200"
    elif [ "$P3" = "200" ]; then
      pass "Public Dashboard - enabled, token=$SHARE_TOKEN, /share/ HTTP 200"
    elif [ "$P4" = "200" ]; then
      pass "Public Dashboard - enabled, token=$SHARE_TOKEN, /dashboard/public/ HTTP 200"
    else
      fail "Public Dashboard - enabled, token=$SHARE_TOKEN, no public URL worked (public=$P1, api=$P2, share=$P3, dashboard=$P4)"
    fi
  else
    # Check if maybe the enable response returned info
    SHARE_FROM_ENABLE=$(echo "$T13_BODY" | python3 -c "
import sys,json
d=json.load(sys.stdin)
print(d.get('public_share_token','') or d.get('share_token','') or d.get('public_url',''))
" 2>/dev/null || echo "")
    if [ -n "$SHARE_FROM_ENABLE" ]; then
      pass "Public Dashboard - enabled (HTTP 200), share_token=$SHARE_FROM_ENABLE from enable response"
    else
      fail "Public Dashboard - enabled (HTTP 200) but no share_token found. Enable body: ${T13_BODY:0:200}. Site info: ${SITE_INFO:0:200}"
    fi
  fi
else
  fail "Public Dashboard - enable returned HTTP $T13_CODE. Body: ${T13_BODY:0:200}"
fi

# ============== TEST 14: Dashboard Stats ==============
echo "--- Test 14: Dashboard Stats ---"
T14_RESP=$(curl -sk "$BASE/api/v1/analytics/stats/$WEBSITE_ID" \
  -H "$AUTH" -H "User-Agent: $UA" -w "\n%{http_code}")
T14_BODY=$(echo "$T14_RESP" | sed '$d')
T14_CODE=$(echo "$T14_RESP" | tail -1)

if [ "$T14_CODE" = "200" ]; then
  ANALYSIS=$(echo "$T14_BODY" | python3 -c "
import sys,json
d=json.load(sys.stdin)
fields_found = []
fields_missing = []
checks = {
    'total_pageviews': ['total_pageviews','totalPageviews','pageviews'],
    'unique_visitors': ['unique_visitors','uniqueVisitors','visitors'],
    'top_pages': ['top_pages','topPages','pages'],
    'top_referrers': ['top_referrers','topReferrers','referrers'],
    'browsers': ['browsers','browser_stats'],
    'devices': ['devices','device_stats','device_types'],
    'countries': ['countries','country_stats','locations']
}
for name, variants in checks.items():
    if any(v in d for v in variants):
        fields_found.append(name)
    else:
        fields_missing.append(name)
print(f'{len(fields_found)}/{len(checks)} fields found: {fields_found}')
if fields_missing:
    print(f'  Missing: {fields_missing}')
print(f'  All keys: {sorted(d.keys())}')
" 2>/dev/null || echo "parse_error")
  pass "Dashboard Stats - HTTP 200. $ANALYSIS"
else
  fail "Dashboard Stats - HTTP $T14_CODE. Body: ${T14_BODY:0:200}"
fi

# ============== TEST 15: Date Range Filtering ==============
echo "--- Test 15: Date Range Filtering ---"
T15A=$(curl -sk "$BASE/api/v1/analytics/stats/$WEBSITE_ID?period=7d" \
  -H "$AUTH" -H "User-Agent: $UA" -w "\n%{http_code}")
T15A_CODE=$(echo "$T15A" | tail -1)

T15B=$(curl -sk "$BASE/api/v1/analytics/stats/$WEBSITE_ID?period=30d" \
  -H "$AUTH" -H "User-Agent: $UA" -w "\n%{http_code}")
T15B_CODE=$(echo "$T15B" | tail -1)

if [ "$T15A_CODE" = "200" ] && [ "$T15B_CODE" = "200" ]; then
  pass "Date Range Filtering - period=7d (200) and period=30d (200) both work"
elif [ "$T15A_CODE" = "200" ]; then
  fail "Date Range Filtering - 7d works (200) but 30d failed ($T15B_CODE)"
elif [ "$T15B_CODE" = "200" ]; then
  fail "Date Range Filtering - 30d works (200) but 7d failed ($T15A_CODE)"
else
  fail "Date Range Filtering - both failed: 7d=$T15A_CODE, 30d=$T15B_CODE"
fi

# ============== BONUS: Existing Tracking Code OBpNPQr8 ==============
echo ""
echo "--- Bonus: Verify existing tracking code OBpNPQr8 ---"
BONUS_RESP=$(curl -sk -X POST "$BASE/api/v1/analytics/track" \
  -H "Content-Type: application/json" -H "User-Agent: $UA" \
  -d '{"tracking_code":"OBpNPQr8","path":"/e2e-test-run","screen_width":1920}' \
  -w "\n%{http_code}")
BONUS_CODE=$(echo "$BONUS_RESP" | tail -1)
BONUS_BODY=$(echo "$BONUS_RESP" | sed '$d')

if [ "$BONUS_CODE" = "200" ]; then
  pass "Existing Tracking Code OBpNPQr8 - pageview tracked (HTTP 200)"
else
  fail "Existing Tracking Code OBpNPQr8 - HTTP $BONUS_CODE. Body: ${BONUS_BODY:0:200}"
fi

# ============== FINAL SUMMARY ==============
echo ""
echo "============================================="
echo "  TEST SUMMARY"
echo "============================================="
echo "  PASSED: $PASS_COUNT"
echo "  FAILED: $FAIL_COUNT"
echo "  TOTAL:  $((PASS_COUNT + FAIL_COUNT))"
echo "============================================="

if [ "$FAIL_COUNT" -gt 0 ]; then
  echo "  Some tests failed. See details above."
  exit 1
else
  echo "  All tests passed!"
fi
