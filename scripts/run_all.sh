#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-trade}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

./scripts/validate.sh "$MODE"
