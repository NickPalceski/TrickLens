"""SSM Parameter Store — the one AWS-touching module app.config itself needs.

Every other AWS-aware module (storage.py, queue.py, auth.py) is built from
app.config.get_settings(). This one is the exception, and has to be: it
exists to produce the value Settings() needs (DATABASE_URL) before Settings
can be constructed at all, so it can't depend on get_settings() the way the
others do — reading AWS_REGION/AWS_ENDPOINT_URL from os.environ directly
below is unavoidable for that reason, not an oversight of the "only
app.config reads os.environ" rule in config.py's docstring.

In dev, DATABASE_URL_SSM_PARAM is never set, so resolve_database_url() is a
no-op and .env's DATABASE_URL is used exactly as before — this module never
touches AWS locally.
"""

import os

import boto3


def resolve_database_url() -> None:
    param_name = os.environ.get("DATABASE_URL_SSM_PARAM")
    if not param_name or os.environ.get("DATABASE_URL"):
        return

    ssm = boto3.client(
        "ssm",
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
        endpoint_url=os.environ.get("AWS_ENDPOINT_URL") or None,
    )
    response = ssm.get_parameter(Name=param_name, WithDecryption=True)
    os.environ["DATABASE_URL"] = response["Parameter"]["Value"]
