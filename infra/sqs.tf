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
    # Must match MAX_RECEIVES in app/worker.py: the last receive gives up on
    # a clip whose runs died instead of crashing into the DLQ.
    maxReceiveCount = 3
  })
}

# Same reasoning as the low maxReceiveCount above: batch_size=1 means one
# poison message can't drag a batch of otherwise-healthy messages down with
# it, since lambda_handler has no per-record failure isolation.
#
# scaling_config caps how many worker runs go at once (the spend ceiling,
# docs/components/infrastructure.md, SQS timings): past it, clips wait in the
# queue instead of starting more 3GB workers. This, not the function's
# reserved_concurrent_executions, because a reserved limit makes Lambda
# throttle: the throttled message goes back to the queue, every bounce counts
# as a receive, and after maxReceiveCount it lands in the DLQ, so a burst
# would end in "analysis failed" clips. Here the trigger just doesn't pick up
# more messages. It also reserves nothing from the account's pool.
resource "aws_lambda_event_source_mapping" "worker" {
  event_source_arn = aws_sqs_queue.analysis.arn
  function_name    = aws_lambda_function.worker.arn
  batch_size       = 1

  scaling_config {
    maximum_concurrency = var.worker_max_concurrency
  }
}
