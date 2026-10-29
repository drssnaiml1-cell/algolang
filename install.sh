#!/usr/bin/env bash
# AlgoLang installer — Linux / macOS
# Usage:  bash install.sh          (offline/mock mode only)
#         bash install.sh --live   (also installs the anthropic SDK for real Claude calls)
set -e
cd "$(dirname "$0")"
ALGO_DIR="$(pwd)"

echo "== AlgoLang installer =="
PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)'; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo "✗ Python 3.9 or newer is required. Install it from https://www.python.org/downloads/ and run this again."
  exit 1
fi
echo "✓ using $($PY --version)"

echo "→ creating virtual environment in .venv"
"$PY" -m venv .venv
.venv/bin/python -m pip install --quiet --upgrade pip
if [ "$1" = "--live" ]; then
  echo "→ installing lark + anthropic"
  .venv/bin/python -m pip install --quiet -r requirements-live.txt
else
  echo "→ installing lark"
  .venv/bin/python -m pip install --quiet -r requirements.txt
fi

chmod +x algo
mkdir -p "$HOME/.local/bin"
ln -sf "$ALGO_DIR/algo" "$HOME/.local/bin/algo"
echo "✓ linked 'algo' command into ~/.local/bin"
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) echo "  note: add this line to ~/.bashrc or ~/.zshrc, then open a new terminal:"
     echo '        export PATH="$HOME/.local/bin:$PATH"' ;;
esac

echo
./algo doctor
echo
echo "Try it:"
echo "  algo run examples/research_brief.algo --arg \"topic=Blockchain data integrity\""
