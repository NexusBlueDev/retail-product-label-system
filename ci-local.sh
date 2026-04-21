#!/usr/bin/env bash
# CI checks for static HTML5/ES6 app (no build tools, no framework).
# ESLint is skipped — no eslint config in this project (static app exception).
# tsc --noEmit covers types.d.ts only (js/ is excluded in tsconfig.json).
set -e

echo "→ tsc --noEmit"
npx --yes tsc --noEmit

echo "✓ CI passed"
touch .ci-verified
