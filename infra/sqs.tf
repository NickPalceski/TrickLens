resource "aws_sqs_queue" "analysis_dlq" {
  name                      = "tricklens-analysis-dlq"
  message_retention_seconds = 1209600 # 14 days — max, to give time to notice and redrive by hand
}

resource "aws_sqs_queue" "analysis" {
  name = "tricklens-analysis"
  # AWS's guidance for a Lambda-triggered queue: at least 6x the function's
  # timeout (300s, infra/lambda.tf). Being merely >= the timeout isn't
  # enough, because the event-source mapping's own retries on a throttled
  # invoke also eat into the window. Lower, and a clip still processing
  # gets delivered a second time. It must also stay above app/worker.py's
  # ANALYZING_LEASE (360s), which is what lets a redelivery recover a clip
  # whose run died.
  visibility_timeout_seconds = 1800

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.analysis_dlq.arn
    # app.worker.lambda_handler has no partial-batch-failure reporting (a
    # single bad record fails the whole invocation, see app/worker.py) —
    # a low maxReceiveCount stops one poison message from retrying forever
    # and burning invocations before it lands in the DLQ.
    maxReceiveCount = 3
  })
}

# Same reasoning as the low maxReceiveCount above: batch_size=1 means one
# poison message can't drag a batch of otherwise-healthy messages down with
# it, since lambda_handler has no per-record failure isolation.
resource "aws_lambda_event_source_mapping" "worker" {
  event_source_arn = aws_sqs_queue.analysis.arn
  function_name    = aws_lambda_function.worker.arn
  batch_size       = 1
}
