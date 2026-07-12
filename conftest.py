"""
Repo-wide pytest isolation guard.

NETBRAIN_MEMORY_DSN must never leak a real Postgres/Supabase connection
string (with password) into a test process. Some code paths under test
(the autonomy/governance faculty stack, via core/copilot_engine.py's
GovernanceEngine.govern()) can trigger a lazy `import app`; importing
app.py runs its module-level _load_secrets_into_env(), which bridges
.streamlit/secrets.toml's real cloud DSN into os.environ as a side effect.
That's invisible to the test that triggered it, but persists in os.environ
for the rest of the pytest process — silently pointing every later
OperationalMemory()/get_operational_memory() default construction at the
real production database instead of the intended local-SQLite fallback.

Found by tracing why tests/test_supply_chain.py started failing (a real
Postgres-only SQL bug in recurring_failures() surfaced) only when run
after tests/test_governed_fix_apply.py in the same process — confirmed
real rows were written to production before that SQL bug crashed the
read-back. Tests that need a guaranteed-local store should also pass an
explicit OperationalMemory(dsn="") (see tests/test_supply_chain.py and
tests/test_governed_fix_apply.py); this fixture is the second, session-wide
layer — it can't undo an already-constructed process-global singleton
mid-test, but it guarantees every test starts and ends with a clean
environment, so pollution from one test can never carry into the next.
"""
import os

import pytest


@pytest.fixture(autouse=True)
def _no_real_memory_dsn_leak():
    os.environ.pop("NETBRAIN_MEMORY_DSN", None)
    yield
    os.environ.pop("NETBRAIN_MEMORY_DSN", None)
