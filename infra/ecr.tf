resource "aws_ecr_repository" "main" {
  name                 = var.ecr_repo_name
  image_tag_mutability = "MUTABLE" # only :latest is ever overwritten; SHA tags are de facto immutable

  image_scanning_configuration {
    scan_on_push = true
  }
}

# Keeps the repo small — every deploy pushes a new SHA tag, and a hobby
# project has no reason to keep more than a handful around for rollback
# (see docs/ARCHITECTURE.md's Rollout decision: rollback is
# `terraform apply -var image_tag=<previous_sha>`, which only works for
# SHAs this policy hasn't expired yet).
resource "aws_ecr_lifecycle_policy" "main" {
  repository = aws_ecr_repository.main.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "keep last 5 images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 5
        }
        action = { type = "expire" }
      }
    ]
  })
}

# The worker's image (step 6a, backend/Dockerfile.worker): the API's base
# plus ffmpeg and the CV stack. A separate repo, not a second tag prefix in
# `main`, so each keeps its own last-5 history. Two images per deploy in one
# repo would halve how far back `-var image_tag=<sha>` can roll back.
# Created by hand once, before the first deploy that pushes to it (README's
# Deployment section): CI pushes images *before* `terraform apply` runs.
resource "aws_ecr_repository" "worker" {
  name                 = var.ecr_worker_repo_name
  image_tag_mutability = "MUTABLE" # same reasoning as `main`

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "worker" {
  repository = aws_ecr_repository.worker.name
  policy     = aws_ecr_lifecycle_policy.main.policy
}
