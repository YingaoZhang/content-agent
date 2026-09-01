from .content import router as content_router
from .pages import router as pages_router
from .system import router as system_router
from .tasks import router as tasks_router

__all__ = ["content_router", "pages_router", "system_router", "tasks_router"]
