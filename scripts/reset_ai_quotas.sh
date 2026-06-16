#!/bin/bash
# Monthly AI Quota Reset Script
# Runs on the 1st of each month at midnight

# Navigate to project directory
cd /home/reda/dev/nordicstats/backend || exit 1

# Execute quota reset in Docker container
docker exec nordicstats-backend python3 -c "
from app.services.ai_quota_service import reset_monthly_quotas
from app.database import SessionLocal

db = SessionLocal()
try:
    count = reset_monthly_quotas(db)
    print(f'Successfully reset AI quotas for {count} users')
except Exception as e:
    print(f'Error resetting AI quotas: {e}')
    exit(1)
finally:
    db.close()
" 2>&1

# Exit with success
exit 0
