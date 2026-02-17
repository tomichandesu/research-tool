#!/usr/bin/env python
"""Web server entry point for Amazon-1688 Research Tool."""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).parent))

import uvicorn
from web.config import settings


def main():
    uvicorn.run(
        "web.app:create_app",
        factory=True,
        host=settings.HOST,
        port=settings.PORT,
        reload=True,
        log_level="info",
    )


if __name__ == "__main__":
    main()
