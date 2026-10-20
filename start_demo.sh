#!/usr/bin/env bash
set -euo pipefail
DEMO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if command -v python3 >/dev/null 2>&1; then
  exec python3 "$DEMO_ROOT/scripts/start_demo.py" "$@"
fi
DEMO_PYTHON="${HOME}/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
if [[ -x "$DEMO_PYTHON" ]]; then
  exec "$DEMO_PYTHON" "$DEMO_ROOT/scripts/start_demo.py" "$@"
fi
printf '%s\n' 'Please install Python 3.12+ or uv, then run this script again.' >&2
exit 1
