#!/bin/bash
#
# Example wrapper script invoked by host crontab (or any external scheduler).
# Duplicate this file per report and update REPORT_NAME accordingly.
#
# `flock` prevents two copies of the same report from running concurrently if
# the previous run is still going.
set -euo pipefail

REPORT_NAME="example_report"

# Adjust these for your install location.
PROJECT_ROOT="${PROJECT_ROOT:-/srv/www/domo-scheduled-ext-reporting}"
PYTHON_BIN="${PYTHON_BIN:-${PROJECT_ROOT}/.venv/bin/python}"
LOCK_FILE="/var/lock/domo-${REPORT_NAME}.lock"

(
  flock -n 9 || { echo "$(date) - ${REPORT_NAME} already running, skipping."; exit 0; }
  cd "${PROJECT_ROOT}"
  "${PYTHON_BIN}" main.py --list "${REPORT_NAME}"
  echo "$(date) - ${REPORT_NAME} - done"
) 9> "${LOCK_FILE}"
