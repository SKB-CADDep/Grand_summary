"""Запуск API для разработки в браузере (конфигурация PyCharm)."""

from __future__ import annotations


def main() -> None:
    from src.bootstrap import ensure_environment

    ensure_environment(frontend=True, build_frontend=False)
    import uvicorn

    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, reload=True)


if __name__ == "__main__":
    main()
