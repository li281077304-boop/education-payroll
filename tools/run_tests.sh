#!/bin/sh
# Unified test entry for this repository.
#
# Why a wrapper instead of a bare `pytest`:
#
# 1. Some launchers (local agent sandboxes, IDE wrappers) inject a
#    sitecustomize shim through PYTHONPATH.  That shim intercepts mkdir() and
#    turns pytest's tmp_path setup into PermissionError, which looks like
#    hundreds of unrelated test errors.  pytest already gets its imports from
#    `pythonpath = [".", "tools"]` in pyproject.toml, so PYTHONPATH is not
#    needed and the shim entry is stripped here.
# 2. The launcher health probe and the in-process HTTP fixtures talk to
#    127.0.0.1.  An exported HTTP_PROXY / ALL_PROXY would route those loopback
#    requests through a local proxy and make an absent port look "foreign".
# 3. pytest's default temp root can be locked down by the same sandbox.  A
#    stable, repo-local temp root keeps runs independent of TMPDIR.
#
# Usage:
#   sh tools/run_tests.sh                 # whole suite
#   sh tools/run_tests.sh tests/test_period_authority.py -q
set -eu

REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$REPO_ROOT"

PYTHON=${PYTHON:-"$REPO_ROOT/.venv/bin/python"}
if [ ! -x "$PYTHON" ]; then
  PYTHON=$(command -v python3)
fi

# Drop only the shim entries; keep any path that points inside this repository.
if [ -n "${PYTHONPATH:-}" ]; then
  CLEAN_PYTHONPATH=$(printf '%s' "$PYTHONPATH" | tr ':' '\n' | grep -v -i 'workbuddy\|/cli/vendor/shim' | paste -sd ':' - || true)
  if [ -n "$CLEAN_PYTHONPATH" ]; then
    PYTHONPATH="$CLEAN_PYTHONPATH"
    export PYTHONPATH
  else
    unset PYTHONPATH
  fi
fi

unset HTTP_PROXY HTTPS_PROXY ALL_PROXY FTP_PROXY http_proxy https_proxy all_proxy ftp_proxy || true
NO_PROXY="localhost,127.0.0.1,::1,0.0.0.0"
no_proxy="$NO_PROXY"
export NO_PROXY no_proxy

BASETEMP=${PAYROLL_TEST_BASETEMP:-"$REPO_ROOT/.pytest-basetemp"}
rm -rf "$BASETEMP"

exec "$PYTHON" -m pytest --basetemp="$BASETEMP" -p no:cacheprovider "$@"
