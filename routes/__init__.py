from routes.auth import auth_router
from routes.students import students_router
from routes.professors import professors_router

__all__ = [
    "auth_router",
    "students_router",
    "professors_router",
]