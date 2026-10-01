"""The real steeze analyzer (step 6). Runs only in the worker image
(Dockerfile.worker), which is the only image with ffmpeg and the CV
libraries. Nothing here may be imported at module level by code the API
image also loads. app/worker.py imports it lazily, inside the "real"
branch, for exactly that reason.
"""
