#!/usr/bin/env bash
# Upload the reviewed public-demo copy of the ORIGINAL app to the user's GitHub.
# Only run from the extracted release folder; does not modify booking_ai_new.
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_NAME="${1:-booking-data-analyst-demo}"

if [[ ! "$REPO_NAME" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "Repository name is invalid: $REPO_NAME" >&2
  exit 2
fi
if ! command -v gh >/dev/null 2>&1; then
  echo "Install GitHub CLI first: brew install gh" >&2
  exit 1
fi
if ! command -v rsync >/dev/null 2>&1; then
  echo "Missing rsync" >&2
  exit 1
fi
if ! gh auth status >/dev/null 2>&1; then
  echo "Please log in: gh auth login" >&2
  exit 1
fi

USERNAME="$(gh api user --jq '.login')"
TARGET="${USERNAME}/${REPO_NAME}"
if ! gh repo view "$TARGET" >/dev/null 2>&1; then
  echo "Creating PUBLIC repository: $TARGET"
  gh repo create "$TARGET" --public --description "Original logistics booking Streamlit app - synthetic public showcase"
fi
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT
gh repo clone "$TARGET" "$WORKDIR/repo"
cd "$WORKDIR/repo"
git checkout -B main

# Replace previous QR demo with the original operational app.
# The release is curated: no user DB, customer documents, credentials or XLSX.
rsync -a --delete \
  --exclude='.git/' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  "$PROJECT_DIR/" "$WORKDIR/repo/"

git add -A
echo
echo "Files to be published / changed in $TARGET:"
git diff --cached --stat
if git diff --cached --quiet; then
  echo "No changes; repository is already up to date."
  gh repo view "$TARGET" --web
  exit 0
fi
printf 'Replace repository files listed above and push to main? [y/N] '
read -r CONFIRM
if [[ "$CONFIRM" != "y" && "$CONFIRM" != "Y" ]]; then
  echo "Cancelled; no commit or push was made."
  exit 0
fi

git -c user.name="${USERNAME}" -c user.email="${USERNAME}@users.noreply.github.com" \
  commit -m "Deploy original logistics app with isolated public demo and analytics"
git push -u origin main
echo
echo "Done: https://github.com/$TARGET"
echo "Streamlit Cloud entry point: app.py (branch: main)"
