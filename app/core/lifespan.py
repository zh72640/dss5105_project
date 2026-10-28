"""Load configuration and own application resources for each ASGI lifespan."""
import sqlite3
from contextlib import ExitStack, asynccontextmanager, closing

from langgraph.checkpoint.sqlite import SqliteSaver

from app.llm.registry import ModelRegistry
from app.api.routes.auth import LoginLimiter
from app.config.bootstrap import load_configuration
from app.core.security import require_initialized


def initialize_checkpoints(db_path):
    """Prepare WAL and checkpoint tables before request handling starts."""
    with closing(sqlite3.connect(str(db_path), timeout=10, check_same_thread=False)) as connection:
        SqliteSaver(connection).get_tuple({"configurable": {"thread_id": "__startup__"}})


@asynccontextmanager
async def lifespan(app, *, settings=None, model_settings=None, model_factory=None, config_overrides=None):
    explicit_settings = settings is not None
    settings, model_settings = load_configuration(settings, model_settings, overrides=config_overrides)
    if not explicit_settings:
        require_initialized(settings.db_path)
    settings = settings.resolve()
    app.state.settings = settings
    app.state.login_limiter = LoginLimiter()

    with ExitStack() as cleanup:
        registry = ModelRegistry(model_settings, model_factory) if model_factory else ModelRegistry(model_settings)
        cleanup.callback(registry.close)
        registry.initialize()
        app.state.model_registry = registry
        initialize_checkpoints(settings.db_path)
        yield
