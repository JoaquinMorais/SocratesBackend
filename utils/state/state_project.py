from sqlmodel import select

from models import Status, StudentProject
from models.state import PROJECT_INSURED
from models.state.state_student_project import (
    Abandoned,
    Active,
    Finished,
    PendingApprovalMember,
    RejectedMember,
)
from utils.statuses import get_status


class ProjectEffector:
    """Aplica en la BD los efectos de entrar a un estado de proyecto."""

    def __init__(self, db):
        self.db = db

    async def save_insured_memory(self, project, previous) -> None:
        """Al desasegurar, recuerda el subestado asegurado para poder retomarlo."""
        if previous.code in PROJECT_INSURED:
            project.id_status_insured = previous.id_status
            self.db.add(project)

    async def finish_memberships(self, project) -> None:
        await self._close_memberships(project, Finished.code)

    async def abandon_memberships(self, project) -> None:
        await self._close_memberships(project, Abandoned.code)

    async def _close_memberships(self, project, active_code: str) -> None:
        rows = (
            await self.db.exec(
                select(StudentProject)
                .join(Status, Status.id_status == StudentProject.id_status)
                .where(
                    StudentProject.id_project == project.id_project,
                    Status.ambito == "student_project",
                    Status.code.in_((Active.code, PendingApprovalMember.code)),
                )
            )
        ).all()
        if not rows:
            return

        rejected = await get_status(self.db, "student_project", RejectedMember.code)
        target = await get_status(self.db, "student_project", active_code)
        for membership in rows:
            if membership.status.code == PendingApprovalMember.code:
                membership.status = rejected
                membership.is_leader = False
            else:
                membership.status = target
            self.db.add(membership)
