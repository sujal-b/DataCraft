import pytest
from fastapi.routing import APIRoute
from starlette.routing import Mount

from main import app


def test_no_api_route_is_shadowed():
    """
    Loop over all routes in app.routes and verify no APIRoute is registered
    after a Mount at '/' (which shadows subsequent routes in Starlette).
    """
    saw_root_mount = False
    for route in app.routes:
        if isinstance(route, Mount) and getattr(route, "path", None) in ("", "/"):
            saw_root_mount = True
        elif saw_root_mount:
            assert not isinstance(route, APIRoute), (
                f"APIRoute '{getattr(route, 'path', str(route))}' is registered after "
                "Mount at '/', which shadows it."
            )
    assert saw_root_mount, "Root mount at '/' not found in app.routes"


def test_no_duplicate_routes():
    """
    Assert that no two APIRoutes in app.routes share the same (path, methods).
    """
    seen_routes = set()
    for route in app.routes:
        if isinstance(route, APIRoute):
            methods = tuple(sorted(route.methods))
            route_key = (route.path, methods)
            assert route_key not in seen_routes, (
                f"Duplicate route found: {route.path} with methods {methods}"
            )
            seen_routes.add(route_key)


def test_health_routes_exist():
    """
    Assert /healthz, /readyz, /api/health/live, /api/health/ready are present.
    """
    expected_paths = {
        "/healthz",
        "/readyz",
        "/api/health/live",
        "/api/health/ready",
    }
    registered_paths = {getattr(route, "path", None) for route in app.routes}
    for path in expected_paths:
        assert path in registered_paths, f"Expected health route '{path}' was not found in app.routes"
