"""Vercel entry point. vercel.json rewrites /api/<anything> to this function."""
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app import app as api  # noqa: E402


async def app(scope, receive, send):
    """Restore the original path, if the platform hands over the rewritten one.

    The rewrite carries the original path in a `path` query parameter, so routing
    works whichever of the two paths the function is given.
    """
    if scope["type"] == "http" and scope.get("path", "").rstrip("/") in ("/api/index", "/api/index.py"):
        query = parse_qsl(scope.get("query_string", b"").decode(), keep_blank_values=True)
        original = next((value for key, value in query if key == "path"), "")
        rest = [(key, value) for key, value in query if key != "path"]
        path = f"/api/{original}" if original else "/api"
        scope = {**scope, "path": path, "raw_path": path.encode(), "query_string": urlencode(rest).encode()}
    await api(scope, receive, send)
