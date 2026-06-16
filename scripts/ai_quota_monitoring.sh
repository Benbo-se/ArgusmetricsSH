#!/bin/bash
# AI Quota Monitoring Script
# Provides real-time insights into AI usage, costs, and quota status

DB_CONTAINER="nordicstats-postgres"
DB_USER="nordicstats"
DB_NAME="nordicstats"

echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║               AI QUOTA MONITORING DASHBOARD                      ║"
echo "╔══════════════════════════════════════════════════════════════════╗"
echo ""

# 1. Overall AI Usage Summary
echo "1. OVERALL AI USAGE SUMMARY"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
docker exec $DB_CONTAINER psql -U $DB_USER -d $DB_NAME -t -c "
SELECT
    plan,
    COUNT(*) as users,
    SUM(ai_chatbot_quota) as total_quota,
    SUM(ai_chatbot_used_this_month) as total_used,
    ROUND(AVG(CASE WHEN ai_chatbot_quota > 0
        THEN (ai_chatbot_used_this_month::float / ai_chatbot_quota * 100)
        ELSE 0 END)::numeric, 1) as avg_usage_pct
FROM users
WHERE plan IS NOT NULL
GROUP BY plan
ORDER BY
    CASE plan
        WHEN 'business' THEN 1
        WHEN 'pro' THEN 2
        WHEN 'starter' THEN 3
        WHEN 'free' THEN 4
    END;
" | awk 'BEGIN {print "Plan       Users  Total Quota  Used  Avg %"} {printf "%-10s %-6s %-12s %-6s %-6s\n", $1, $2, $3, $4, $5}'
echo ""

# 2. Users Near Quota Limit (>80%)
echo "2. USERS APPROACHING QUOTA LIMIT (>80%)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
docker exec $DB_CONTAINER psql -U $DB_USER -d $DB_NAME -t -c "
SELECT
    email,
    plan,
    ai_chatbot_used_this_month as used,
    ai_chatbot_quota as quota,
    ROUND((ai_chatbot_used_this_month::float / ai_chatbot_quota * 100)::numeric, 1) as pct
FROM users
WHERE ai_chatbot_quota > 0
  AND (ai_chatbot_used_this_month::float / ai_chatbot_quota) >= 0.8
ORDER BY pct DESC
LIMIT 10;
" | head -15
echo ""

# 3. Users Who Exceeded Quota
echo "3. USERS WHO EXCEEDED QUOTA (100%)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
quota_exceeded=$(docker exec $DB_CONTAINER psql -U $DB_USER -d $DB_NAME -t -c "
SELECT COUNT(*)
FROM users
WHERE ai_chatbot_quota > 0
  AND ai_chatbot_used_this_month >= ai_chatbot_quota;
")
echo "Total users exceeded: $quota_exceeded"

if [ "$quota_exceeded" -gt 0 ]; then
    docker exec $DB_CONTAINER psql -U $DB_USER -d $DB_NAME -t -c "
    SELECT
        email,
        plan,
        ai_chatbot_used_this_month as used,
        ai_chatbot_quota as quota
    FROM users
    WHERE ai_chatbot_quota > 0
      AND ai_chatbot_used_this_month >= ai_chatbot_quota
    ORDER BY ai_chatbot_used_this_month DESC
    LIMIT 10;
    " | head -15
fi
echo ""

# 4. Estimated AI Costs This Month
echo "4. ESTIMATED AI COSTS THIS MONTH"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
docker exec $DB_CONTAINER psql -U $DB_USER -d $DB_NAME -t -c "
SELECT
    plan,
    COUNT(*) as users,
    SUM(ai_chatbot_used_this_month) as total_messages,
    CASE plan
        WHEN 'starter' THEN ROUND(SUM(ai_chatbot_used_this_month) * 0.01, 2)
        WHEN 'pro' THEN ROUND(SUM(ai_chatbot_used_this_month) * 0.0035, 2)
        WHEN 'business' THEN ROUND(SUM(ai_chatbot_used_this_month) * 0.0008, 2)
        ELSE 0
    END as estimated_cost
FROM users
WHERE ai_chatbot_quota > 0
GROUP BY plan
ORDER BY
    CASE plan
        WHEN 'business' THEN 1
        WHEN 'pro' THEN 2
        WHEN 'starter' THEN 3
    END;
" | awk 'BEGIN {print "Plan       Users  Messages  Est. Cost ($)"} {printf "%-10s %-6s %-9s $%-10s\n", $1, $2, $3, $4}'

total_cost=$(docker exec $DB_CONTAINER psql -U $DB_USER -d $DB_NAME -t -c "
SELECT ROUND(
    SUM(CASE plan
        WHEN 'starter' THEN ai_chatbot_used_this_month * 0.01
        WHEN 'pro' THEN ai_chatbot_used_this_month * 0.0035
        WHEN 'business' THEN ai_chatbot_used_this_month * 0.0008
        ELSE 0
    END), 2)
FROM users
WHERE ai_chatbot_quota > 0;
")
echo ""
echo "TOTAL ESTIMATED COST: \$$total_cost"
echo ""

# 5. Next Quota Reset
echo "5. NEXT QUOTA RESET"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
docker exec $DB_CONTAINER psql -U $DB_USER -d $DB_NAME -t -c "
SELECT
    MIN(ai_quota_reset_date)::date as next_reset,
    COUNT(DISTINCT ai_quota_reset_date::date) as unique_reset_dates
FROM users
WHERE ai_quota_reset_date IS NOT NULL;
"
echo ""

# 6. Potential Upgrade Candidates
echo "6. POTENTIAL UPGRADE CANDIDATES (70-99% usage)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
upgrade_candidates=$(docker exec $DB_CONTAINER psql -U $DB_USER -d $DB_NAME -t -c "
SELECT COUNT(*)
FROM users
WHERE ai_chatbot_quota > 0
  AND (ai_chatbot_used_this_month::float / ai_chatbot_quota) BETWEEN 0.7 AND 0.99;
")
echo "Total upgrade candidates: $upgrade_candidates"

if [ "$upgrade_candidates" -gt 0 ]; then
    docker exec $DB_CONTAINER psql -U $DB_USER -d $DB_NAME -t -c "
    SELECT
        email,
        plan,
        ROUND((ai_chatbot_used_this_month::float / ai_chatbot_quota * 100)::numeric, 1) as usage_pct,
        CASE plan
            WHEN 'starter' THEN 'Upgrade to Pro (1,000 msgs)'
            WHEN 'pro' THEN 'Upgrade to Business (10,000 msgs)'
            ELSE 'N/A'
        END as recommendation
    FROM users
    WHERE ai_chatbot_quota > 0
      AND (ai_chatbot_used_this_month::float / ai_chatbot_quota) BETWEEN 0.7 AND 0.99
    ORDER BY usage_pct DESC
    LIMIT 10;
    " | head -15
fi
echo ""

# 7. Zero Usage (Inactive AI Users)
echo "7. INACTIVE AI USERS (0 usage this month)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
inactive=$(docker exec $DB_CONTAINER psql -U $DB_USER -d $DB_NAME -t -c "
SELECT
    plan,
    COUNT(*) as inactive_users
FROM users
WHERE ai_chatbot_quota > 0
  AND (ai_chatbot_used_this_month IS NULL OR ai_chatbot_used_this_month = 0)
GROUP BY plan;
")
echo "$inactive"
echo ""

echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║                    MONITORING COMPLETE                           ║"
echo "╚══════════════════════════════════════════════════════════════════╝"
echo ""
echo "Generated: $(date '+%Y-%m-%d %H:%M:%S')"
