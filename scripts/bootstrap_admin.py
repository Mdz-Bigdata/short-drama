#!/usr/bin/env python3
"""Initialize platform tables and create the one-time development administrator."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.platform.bootstrap import initialize_platform  # noqa: E402
from app.platform.dependencies import get_platform_store  # noqa: E402


async def main() -> None:
    store = get_platform_store()
    result = await initialize_platform(store)
    login = result.get("admin_login") or "admin@short-drama"
    if result["admin_created"]:
        print(f"Administrator created: {login}")
    else:
        print(f"Administrator already exists: {login}")
    if result.get("credential_file"):
        print(f"One-time credential file: {result['credential_file']}")
    await store.close()


if __name__ == "__main__":
    asyncio.run(main())
