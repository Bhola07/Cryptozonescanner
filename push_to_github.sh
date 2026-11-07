#!/usr/bin/env bash
# Usage: ./push_to_github.sh https://github.com/yourname/crypto-zone-scanner.git
set -euo pipefail

if [ $# -ne 1 ]; then
  echo "Usage: $0 <your-github-repo-url>"
  exit 1
fi

REPO_URL="$1"

git init -q
git add .
git commit -m "Initial commit: crypto zone scanner MVP" || echo "Nothing new to commit"
git branch -M main
git remote remove origin 2>/dev/null || true
git remote add origin "$REPO_URL"
git push -u origin main

echo "Done. Your code is at: ${REPO_URL%.git}"
