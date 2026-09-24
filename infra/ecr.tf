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
