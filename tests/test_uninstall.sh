#!/usr/bin/env bash
# Isolated fixtures only; never operate on production services.
set -Eeuo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
export PYTHONPATH="$PWD/tests${PYTHONPATH:+:$PYTHONPATH}"
exec "${PYTHON_BIN:-python3}" -m unittest -v test_manager.ManagerTest.test_uninstall_cancellation_preserves_deployment test_manager.ManagerTest.test_uninstall_backs_up_and_preserves_external_certs_and_unknown_files test_manager.ManagerTest.test_uninstall_refuses_modified_service test_manager.ManagerTest.test_uninstall_refuses_symlinked_binary "$@"
