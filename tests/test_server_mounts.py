from starlette.routing import Mount

from backend.server.app import FRONTEND_DIR, app


def _count_mounts(path: str) -> int:
    return sum(1 for route in app.routes if isinstance(route, Mount) and route.path == path)


def test_mounts_are_not_duplicated():
    assert _count_mounts("/outputs") == 1
    assert _count_mounts("/site") == (1 if FRONTEND_DIR.exists() else 0)
    assert _count_mounts("/static") == (1 if (FRONTEND_DIR / "static").exists() else 0)
