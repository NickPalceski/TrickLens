"""app.logs.configure_logging() under a Lambda-style logging setup.

In Lambda the runtime has already attached its handler to the root logger,
and the root stays at WARNING. Our INFO lines were silently dropped there
from step 5 until 6b (see app/logs.py). Each case runs in a fresh
interpreter, so pytest's own logging setup can't mask the behaviour.
"""

import subprocess
import sys

_LAMBDA_LIKE = """
import io, logging
buf = io.StringIO()
logging.getLogger().addHandler(logging.StreamHandler(buf))  # the runtime's handler
{setup}
logging.getLogger("tricklens.worker").info("stage A: 1 trick(s)")
print(repr(buf.getvalue()))
"""


def _run(setup: str) -> str:
    out = subprocess.run(
        [sys.executable, "-c", _LAMBDA_LIKE.format(setup=setup)],
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout


def test_reproduces_the_bug_without_configure_logging():
    """Control: what main.py/worker.py effectively did in Lambda before."""
    assert "stage A" not in _run("logging.basicConfig(level=logging.INFO)  # a no-op here")


def test_info_reaches_the_runtime_handler_with_configure_logging():
    out = _run("from app.logs import configure_logging; configure_logging()")
    assert "stage A: 1 trick(s)" in out
