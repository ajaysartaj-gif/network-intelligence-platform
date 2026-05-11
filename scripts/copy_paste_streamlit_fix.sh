#!/usr/bin/env bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

echo "Checking app.py for pasted shell/patch text..."

python - <<'PY'
from pathlib import Path
import subprocess
import py_compile

path = Path("app.py")
text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
first_25_lines = "\n".join(text.splitlines()[:25])
markers = [
    "git apply --3way <<",
    "git apply <<",
    "git rev-parse --show-toplevel",
    "*** Begin Patch",
    "*** End Patch",
]

looks_bad = any(marker in first_25_lines for marker in markers)
looks_bad = looks_bad or first_25_lines.lstrip().startswith("(cd ")

if looks_bad:
    print("app.py contains pasted shell/patch text. Restoring app.py from git HEAD...")
    subprocess.check_call(["git", "restore", "--source=HEAD", "--", "app.py"])
else:
    print("app.py header looks clean. No restore needed.")

py_compile.compile("app.py", doraise=True)
print("SUCCESS: app.py is valid Python now.")
PY

echo "Done. Reboot/redeploy your Streamlit app from the latest GitHub commit."
