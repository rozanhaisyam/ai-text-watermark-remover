"""Deployment entry point for the Unwatermark FastAPI application.

Both ``uvicorn main:app`` and ``python main.py`` use the same application as
``uvicorn app:app``. The latter command reads the platform's PORT variable.
"""

from app import app  # re-export for ASGI servers


if __name__ == "__main__":
    import os

    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
