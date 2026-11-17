#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
repo="${1:-booking-data-analyst-demo}"
if ! command -v gh >/dev/null 2>&1; then
  echo 'Chưa có GitHub CLI. Hãy chạy: brew install gh'
  exit 1
fi
if ! command -v git >/dev/null 2>&1; then
  echo 'Chưa có git.'
  exit 1
fi
if ! gh auth status >/dev/null 2>&1; then
  echo 'Chưa đăng nhập GitHub CLI. Hãy chạy: gh auth login'
  exit 1
fi
if [[ -d .git ]]; then
  echo 'Thư mục này đã có .git; không tự tạo/push để tránh ghi nhầm lên repo hiện có.'
  exit 1
fi
if [[ ! "$repo" =~ ^[a-zA-Z0-9_.-]+$ ]]; then
  echo 'Tên repository không hợp lệ.'
  exit 1
fi
git init -b main
git add .
git commit -m 'Publish Booking Data Analyst demo (synthetic data only)'
echo "Đang tạo repository PUBLIC: $repo"
gh repo create "$repo" --public --source=. --remote=origin --push
printf '\nĐÃ PUSH. Repo: '
gh repo view --json url --jq .url
printf 'Triển khai app: https://share.streamlit.io/ (main file: streamlit_app.py)\n'
