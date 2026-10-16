"""Load configuration and own application resources for each ASGI lifespan."""
from contextlib import ExitStack, asynccontextmanager

from app.llm.registry import ModelRegistry
from app.agent.checkpoints import initialize_checkpoints
from app.api.routes.auth import LoginLimiter
from app.config.bootstrap import load_configuration
from app.core.security import require_initialized


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
