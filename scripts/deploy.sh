#!/bin/bash
# Manual Vercel deployment fallback
# Primary deploy is auto-deploy via GitHub integration (push to main)
# Only use this if auto-deploy fails or you need to force a redeploy
#
# Usage: ./scripts/deploy.sh

set -e

VERCEL_TOKEN=$(grep '^VERCEL_TOKEN=' .env.local | cut -d= -f2-)
TEAM_ID=$(grep '^VERCEL_TEAM_ID=' .env.local | cut -d= -f2-)
PROJECT_ID=$(grep '^VERCEL_PROJECT_ID=' .env.local | cut -d= -f2-)

if [ -z "$VERCEL_TOKEN" ] || [ -z "$TEAM_ID" ] || [ -z "$PROJECT_ID" ]; then
    echo "Error: VERCEL_TOKEN, VERCEL_TEAM_ID, and VERCEL_PROJECT_ID required in .env.local"
    exit 1
fi

echo "Triggering Vercel deployment for retail-product-label-system..."
echo "Target: retail-scanner-nii.nexusblue.ai"

RESPONSE=$(curl -s -X POST "https://api.vercel.com/v13/deployments?teamId=$TEAM_ID" \
  -H "Authorization: Bearer $VERCEL_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"name\": \"retail-product-label-system\",
    \"project\": \"$PROJECT_ID\",
    \"gitSource\": {
      \"type\": \"github\",
      \"org\": \"NexusBlueDev\",
      \"repo\": \"retail-product-label-system\",
      \"ref\": \"main\"
    },
    \"target\": \"production\"
  }")

URL=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('url','ERROR'))" 2>/dev/null)
ERROR=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('error',{}).get('message',''))" 2>/dev/null)

if [ -n "$ERROR" ] && [ "$ERROR" != "" ]; then
    echo "Deploy failed: $ERROR"
    exit 1
fi

echo "Deploy triggered: https://$URL"
echo "Production URL: https://retail-scanner-nii.nexusblue.ai"
