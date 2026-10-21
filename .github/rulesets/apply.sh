#!/usr/bin/env bash
# Creates or updates the repository rulesets in this folder (matched by name).
# Needs a gh login with admin rights on the repo. Run from anywhere:
#   .github/rulesets/apply.sh [owner/repo]
set -euo pipefail
repo="${1:-Niecke/lumios}"
dir="$(cd "$(dirname "$0")" && pwd)"

for file in "$dir"/*.json; do
  name="$(jq -r .name "$file")"
  id="$(gh api "repos/$repo/rulesets" --jq ".[] | select(.name == \"$name\") | .id")"
  if [ -n "$id" ]; then
    gh api --method PUT "repos/$repo/rulesets/$id" --input "$file" --silent
    echo "updated $name ($id)"
  else
    gh api --method POST "repos/$repo/rulesets" --input "$file" --silent
    echo "created $name"
  fi
done
