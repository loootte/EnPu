"""
FastAPI entrypoint for EnPu core.

Implement in GitHub issue #2:
  - FastAPI app with CORS
  - GET /health
  - POST /v1/recognize (mock, then real pipeline in #3)

Target start command (from core/ with venv active):

    uvicorn app.main:app --reload --host 127.0.0.1 --port 8765
"""

# from fastapi import FastAPI
#
# app = FastAPI(title="EnPu Core", version="0.0.0")
#
# @app.get("/health")
# def health() -> dict[str, str]:
#     return {"status": "ok"}
