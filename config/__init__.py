"""Config package shims for the top-level config module.

Some parts of the code import configuration via ``from config import ...``.
When a ``config`` package directory exists it shadows the top-level
``config.py`` module. To preserve compatibility for the few values
imported as ``from config import ...``, re-export the expected
constants here.
"""

# Keep these values in sync with `/workspaces/network-intelligence-platform/config.py`.
MAX_CHAT_HISTORY = 20
MAX_RESULTS_STORED = 5
TTL_SIMULATION_MINUTES = 30
TTL_RESULTS_MINUTES = 60

import importlib.util
import os
from pathlib import Path


# Try to locate the top-level `config.py` and import its uppercase symbols
# so existing code that does `from config import ...` continues to work.
try:
	root_config_path = Path(__file__).resolve().parents[1] / "config.py"
	if root_config_path.exists():
		spec = importlib.util.spec_from_file_location("_root_config", str(root_config_path))
		_root_config = importlib.util.module_from_spec(spec)
		spec.loader.exec_module(_root_config)

		for name in dir(_root_config):
			if name.isupper() and name not in globals():
				globals()[name] = getattr(_root_config, name)
except Exception:
	# Best-effort only; if this fails, module still exports the minimal constants above.
	pass

# If you prefer a single source of truth, consider removing the top-level
# `config.py` or moving all settings into this package and updating imports.

