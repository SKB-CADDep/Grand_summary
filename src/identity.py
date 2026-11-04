from __future__ import annotations

import getpass
import os

from fastapi import Request


def current_user(request: Request | None = None) -> str:
    """Windows-имя: заголовок прокси, иначе USERNAME / getuser()."""
    if request is not None:
        header = request.headers.get("X-Remote-User") or request.headers.get("Remote-User")
        if header:
            return header.split("\\")[-1].strip()
    return os.environ.get("USERNAME") or os.environ.get("USER") or getpass.getuser()
