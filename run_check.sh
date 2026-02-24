#!/usr/bin/env bash
set -euo pipefail

DAY8="${1:-}"
python3 ./ci_check.py "$DAY8"
