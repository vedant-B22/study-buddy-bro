#!/bin/bash
cd ~/study-buddy-bro-guide_agent
git add .
git diff --cached --quiet && echo "Nothing to push" && exit 0
git commit -m "Auto update: $(date '+%Y-%m-%d %H:%M')"
git pull origin main --rebase
git push origin main
echo "✅ GitHub updated!"
