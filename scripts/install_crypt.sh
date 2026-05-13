#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-}"

if [[ -z "$PYTHON" ]]; then
  if command -v python3.13 >/dev/null 2>&1; then
    PYTHON="python3.13"
  elif command -v python3 >/dev/null 2>&1; then
    PYTHON="python3"
  elif command -v python >/dev/null 2>&1; then
    PYTHON="python"
  else
    echo "No Python found. Install Python 3.13 or set PYTHON=/path/to/python." >&2
    exit 1
  fi
fi

BIN="${HOME}/.crypt/bin"
mkdir -p "$BIN"

echo "== Crypt install/link =="
echo "root: $ROOT"
echo "python: $PYTHON"

echo
echo "== Compile =="
"$PYTHON" -m compileall -q "$ROOT/main.py" "$ROOT/core" "$ROOT/tools" "$ROOT/crypt"

echo
echo "== Editable package install =="
"$PYTHON" -m pip install -e "$ROOT"

cat > "$BIN/crypt" <<EOF
#!/usr/bin/env bash
exec "$PYTHON" "$ROOT/main.py" "\$@"
EOF
chmod +x "$BIN/crypt"

echo
echo "Linked command: $BIN/crypt"
case ":$PATH:" in
  *":$BIN:"*) ;;
  *) echo "Add this to PATH if needed: export PATH=\"\$HOME/.crypt/bin:\$PATH\"" ;;
esac

echo "Try from any project: crypt doctor"
