# Source Integrity Recovery

If Streamlit reports an error like this while opening the app:

```text
File "/mount/src/network-intelligence-platform/app.py", line 1
(cd "$(git rev-parse --show-toplevel)" && git apply --3way <<'EOF'
^
IndentationError: unexpected indent
```

then a shell patch command was pasted into `app.py` instead of being executed in a terminal.

## Fix

1. Restore `app.py` from git:

   ```bash
   git checkout -- app.py
   ```

2. If other Python files were edited the same way, restore them too or run:

   ```bash
   git status --short
   git checkout -- path/to/corrupted_file.py
   ```

3. Run the source integrity check:

   ```bash
   python scripts/check_source_integrity.py
   ```

4. Run the Python syntax check:

   ```bash
   python -m py_compile app.py
   ```

## One-command local repair

If your local checkout has the pasted shell command at the top of `app.py`, run:

```bash
python scripts/repair_pasted_patch.py app.py
```

This restores only files that clearly contain pasted patch/shell text in their first lines, then verifies Python syntax. If the command reports that `app.py` is already clean but Streamlit Cloud still shows the old error, redeploy from the latest GitHub commit or reboot the Streamlit app because the deployed copy is stale.

## Prevention

Patch blocks that start with `git apply`, `cat > file`, or `*** Begin Patch` must be run in a terminal or applied by a development tool. They should never be pasted into `app.py` or any other Python source file.
