#!/bin/bash
# push-both.sh — Push a axon-lang (public) Y axon-enterprise (private) simultaneously

set -e

BRANCH="${1:-master}"

echo "🚀 Pushing to both repositories..."
echo "   Branch: $BRANCH"
echo ""

# Fetch latest from both remotes
echo "📥 Fetching from both remotes..."
git fetch origin
git fetch enterprise

# Push to origin (axon-lang — public)
echo "📤 Pushing to origin (axon-lang — PUBLIC)..."
git push origin "$BRANCH"
echo "   ✅ origin/master synced"

# Push to enterprise (axon-enterprise — private)
echo "📤 Pushing to enterprise (axon-enterprise — PRIVATE)..."
git push enterprise "$BRANCH"
echo "   ✅ enterprise/master synced"

echo ""
echo "✨ Both repositories synchronized!"
echo ""
echo "Current state:"
git log --oneline -3
