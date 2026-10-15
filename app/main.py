"""FastAPI factory, also usable with uvicorn app.main:create_app --factory."""
from functools import partial
from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse
from app import APP_VERSION
from app.api.errors import install_handlers
from app.api.middleware import RequestPolicy
from app.api.routes import router
from app.config.settings import ROOT, Settings
from app.core.lifespan import lifespan


def create_app(settings: Settings | None = None, *, model_settings=None, model_factory=None,
               config_overrides=None):
    startup = partial(lifespan, settings=settings, model_settings=model_settings,
                      model_factory=model_factory, config_overrides=dict(config_overrides or {}))
    app = FastAPI(title="SweaterCo Dispatch Desk", version=APP_VERSION,
        description="SQLite dispatch desk. Use Chat v2 for preview and explicit confirmation; "
                    "production events use /api/events.",
        lifespan=startup)
    app.add_middleware(RequestPolicy)
    install_handlers(app)
    app.include_router(router)
    def openapi():
        if app.openapi_schema is None:
            schema = get_openapi(title=app.title, version=app.version, description=app.description, routes=app.routes)
            for path in schema["paths"].values():
                for operation in path.values():
                    if isinstance(operation, dict):
                        responses = operation.get("responses", {})
                        if "422" in responses:
                            responses.pop("422")
                            responses.setdefault("400", {"description": "Invalid request"})
            app.openapi_schema = schema
        return app.openapi_schema
    app.openapi = openapi
    for path, filename, mime in (
        ("/", "index.html", "text/html"),
        ("/desk.js", "desk.js", "text/javascript"),
        ("/desk.css", "desk.css", "text/css"),
        ("/chat", "chat.html", "text/html"), ("/chat.css", "chat.css", "text/css"),
        ("/chat.js", "chat.js", "text/javascript"), ("/chat-common.js", "chat-common.js", "text/javascript"),
        ("/desk-chat.js", "desk-chat.js", "text/javascript")):
        # No arbitrary filesystem paths are exposed.
        def asset_factory(name, media_type):
            def asset():
                return FileResponse(ROOT / "app/ui" / name, media_type=media_type)
            return asset
        app.add_api_route(path, asset_factory(filename, mime), methods=["GET"], include_in_schema=False)
    return app
