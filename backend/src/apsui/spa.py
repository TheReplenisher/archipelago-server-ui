"""Serve the built React app, falling back to index.html for client-side routes."""

from typing import Any

from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope


class SPAStaticFiles(StaticFiles):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(html=True, **kwargs)

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            # Unknown API paths must stay 404s, not turn into the app shell.
            if exc.status_code != 404 or path == "api" or path.startswith("api/"):
                raise
            return await super().get_response("index.html", scope)
