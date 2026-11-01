#!/usr/bin/env bash
# Isolated fixtures only; never operate on production services.
set -Eeuo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
export PYTHONPATH="$PWD/tests${PYTHONPATH:+:$PYTHONPATH}"
exec "${PYTHON_BIN:-python3}" -m unittest -v test_bootstrap test_manager.ManagerTest.test_installer_refuses_existing_user_config "$@"
