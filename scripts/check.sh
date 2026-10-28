#!/usr/bin/env sh
# Everything a change must pass, backend and app, in one command:
#   scripts/check.sh            (from the repository root)
set -eu
cd "$(dirname "$0")/.."

echo "== backend: lint"
ruff check techflip tests scripts
echo "== backend: tests"
python -m pytest -q

if [ -d mobile/node_modules ]; then
  echo "== app: types"
  (cd mobile && npx tsc --noEmit)
  echo "== app: lint"
  (cd mobile && npx expo lint)
else
  echo "== app: skipped (run 'npm install' in mobile/ first)"
fi
echo "OK"
