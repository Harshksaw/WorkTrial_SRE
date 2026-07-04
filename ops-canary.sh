#!/usr/bin/env bash
# Backward-compatible wrapper kept for reviewers who notice the original file name.
# Prefer: bash ops canary <version> [location] [--bad]
set -euo pipefail
exec bash ops canary "$@"
