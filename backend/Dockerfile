# Built on the AWS Lambda Python base image.
#
# This is deliberate: the image that runs on your laptop is the same image
# that runs in Lambda — same base, same layers, same digest. Locally we
# override the entrypoint (see docker-compose.yml) to run uvicorn with
# hot-reload; in production the Lambda runtime invokes app.lambda_handler.
# "Works on my machine" stops being a category of bug.
FROM public.ecr.aws/lambda/python:3.12

# Dependencies are installed before the source is copied so that editing code
# does not invalidate the (slow) dependency layer.
COPY requirements.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt

COPY alembic.ini ${LAMBDA_TASK_ROOT}/
COPY alembic/ ${LAMBDA_TASK_ROOT}/alembic/
COPY app/ ${LAMBDA_TASK_ROOT}/app/

# Lambda's production entrypoint. Ignored locally.
CMD ["app.lambda_handler.handler"]
