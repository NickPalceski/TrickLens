"""Logging setup shared by every entrypoint (API, worker, rankings).

One function, called at import by each entrypoint module, because the two
environments need opposite things:

- **Locally** nothing has configured logging yet, so basicConfig() installs
  a stderr handler at INFO (what `docker compose logs` shows).
- **In Lambda** the runtime has already put its own handler on the root
  logger, so basicConfig() is a silent no-op, and the root logger stays at
  Python's default WARNING. Every `log.info()` from our code was dropped
  before reaching CloudWatch. That went unnoticed from step 5 until the 6b
  prod check went looking for the worker's `stage A:` line and found
  nothing.

The fix is to set the level on our own `tricklens` logger instead of the
root. Records from `tricklens.*` then pass their logger's level check and
propagate to whatever handler the root has: Lambda's in prod, basicConfig's
locally.
"""

import logging

_FORMAT = "%(asctime)s %(levelname)-8s %(name)s | %(message)s"


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format=_FORMAT)  # no-op under Lambda
    logging.getLogger("tricklens").setLevel(logging.INFO)
