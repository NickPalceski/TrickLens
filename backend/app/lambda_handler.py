"""Production entrypoint.

Mangum translates Lambda's (event, context) calling convention into ASGI, so
the same FastAPI app serves both `uvicorn` locally and Lambda in production
with no changes.
"""

from mangum import Mangum

from app.main import app

handler = Mangum(app, lifespan="off")
