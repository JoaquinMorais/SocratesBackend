from routes.auth import auth_router
from routes.me import me_router
from routes.students import students_router
from routes.professors import professors_router
from routes.users import users_router
from routes.sections import sections_router
from routes.section_years import section_years_router
from routes.professor_section_years import professor_section_years_router

__all__ = [
    "auth_router",
    "me_router",
    "students_router",
    "professors_router",
    "users_router",
    "sections_router",
    "section_years_router",
    "professor_section_years_router",
]