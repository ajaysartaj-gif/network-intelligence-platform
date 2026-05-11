"""Repair Python files that were overwritten with pasted shell patch commands.

Use this when Streamlit reports an error similar to:

    File ".../app.py", line 1
       (shell patch command pasted into Python source)
      ^
    IndentationError: unexpected indent

The repair is intentionally conservative: it only restores files whose first
lines clearly look like a pasted patch/shell wrapper.
"""

from __future__ import annotations

import argparse
import py_compile
import subprocess
import sys
from pathlib import Path

PATCH_MARKERS = (
    "git " + "apply --3way <<",
    "git " + "apply <<",
    "git " + "rev-parse --show-toplevel",
    "*** Begin " + "Patch",
    "*** End " + "Patch",
)


def repo_root() -> Path:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        return Path(out)
    except Exception:
        return Path(__file__).resolve().parents[1]


def looks_corrupted(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, "missing"
    head = "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[:25])
    for marker in PATCH_MARKERS:
        if marker in head:
            return True, marker
    first = head.lstrip().splitlines()[0] if head.strip() else ""
    if first.startswith("(cd ") and "git" in first and "apply" in first:
        return True, first[:120]
    return False, ""


def restore_from_git(root: Path, rel_path: str) -> None:
    subprocess.check_call(["git", "restore", "--source=HEAD", "--", rel_path], cwd=root)


def compile_file(path: Path) -> None:
    py_compile.compile(str(path), doraise=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Restore app.py or other Python files if a git-apply patch command was pasted into them."
    )
    parser.add_argument(
        "files",
        nargs="*",
        default=["app.py"],
        help="Repository-relative Python files to inspect and repair. Defaults to app.py.",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only report corruption; do not restore files from git.",
    )
    args = parser.parse_args()

    root = repo_root()
    repaired: list[str] = []
    clean: list[str] = []
    failed: list[str] = []

    for rel in args.files:
        path = root / rel
        bad, marker = looks_corrupted(path)
        if not bad:
            clean.append(rel)
            continue

        if args.check_only:
            failed.append(f"{rel}: corrupted marker found ({marker})")
            continue

        try:
            restore_from_git(root, rel)
            compile_file(path)
            repaired.append(rel)
        except Exception as exc:
            failed.append(f"{rel}: repair failed: {exc}")

    for rel in clean:
        print(f"OK: {rel} does not contain pasted patch text in the file header.")
    for rel in repaired:
        print(f"REPAIRED: restored {rel} from git HEAD and verified Python syntax.")
    for item in failed:
        print(f"FAILED: {item}", file=sys.stderr)

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
