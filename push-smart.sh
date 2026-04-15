#!/bin/bash
# push-smart.sh — Smart push que entiende qué commits van a dónde

set -e

BRANCH="${1:-master}"

echo "🔍 Analyzing commits for routing..."
echo ""

# Obtener commits no pusheados
COMMITS=$(git log origin/master..HEAD --pretty=format:"%h %s" 2>/dev/null || echo "")

if [ -z "$COMMITS" ]; then
    echo "ℹ️  No new commits to push"
    exit 0
fi

echo "📋 Commits pendientes:"
echo "$COMMITS"
echo ""

# Detectar si hay cambios enterprise
ENTERPRISE_FILES="axon-enterprise\|rbac\|sso\|audit\|metering\|LICENSE.commercial"
HAS_ENTERPRISE=$(git diff origin/master..HEAD --name-only | grep -E "$ENTERPRISE_FILES" || echo "")

if [ -n "$HAS_ENTERPRISE" ]; then
    echo "⚠️  Enterprise features detected!"
    echo ""
    echo "📤 Pushing to BOTH repositories:"
    echo "   1. origin (axon-lang — public)"
    echo "   2. enterprise (axon-enterprise — private)"
    echo ""

    git push origin "$BRANCH"
    git push enterprise "$BRANCH"

    echo "✅ Both synced (core + enterprise features)"
else
    echo "✅ Only open-source changes detected"
    echo ""
    echo "📤 Pushing to origin only (axon-lang — public)"
    git push origin "$BRANCH"

    echo "💡 To sync with enterprise later:"
    echo "   cd ../axon-enterprise && ./sync-from-upstream.sh"
fi

echo ""
echo "Done! Current HEAD:"
git log -1 --oneline
