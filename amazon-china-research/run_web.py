#!/usr/bin/env python
"""Web server entry point for Amazon-1688 Research Tool."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).parent))

import uvicorn
from web.config import settings


def main():
    # reload=True is for development only. In production (Docker),
    # set UVICORN_RELOAD=false (default) to prevent WatchFiles from
    # killing running research jobs when files are updated via deploy.
    reload = os.environ.get("UVICORN_RELOAD", "false").lower() in ("1", "true", "yes")
    uvicorn.run(
        "web.app:create_app",
        factory=True,
        host=settings.HOST,
        port=settings.PORT,
        reload=reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
