from sqlmodel import select

from models import Status, StudentProject, StudentSectionYear
from models.state import PROJECT_INSURED
from models.state.state_student_project import (
    Abandoned,
    Active,
    Finished,
    PendingApprovalMember,
    RejectedMember,
)
from models.state.student_section_year import (
    ATTENDING,
    FINISHED_APPROVED,
    FINISHED_FAILED,
)
from utils.state.student_section_year import apply_cursada_transition
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
        await self._close_memberships(project, Finished.code, FINISHED_APPROVED)

    async def cancel_memberships(self, project) -> None:
        await self._close_memberships(project, Abandoned.code, FINISHED_FAILED)

    async def _close_memberships(
        self, project, active_code: str, cursada_state: str
    ) -> None:
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
        active_students = [
            membership.id_student
            for membership in rows
            if membership.status.code == Active.code
        ]
        for membership in rows:
            if membership.status.code == PendingApprovalMember.code:
                membership.status = rejected
                membership.is_leader = False
            else:
                membership.status = target
            self.db.add(membership)

        if active_students:
            cursadas = (
                await self.db.exec(
                    select(StudentSectionYear).where(
                        StudentSectionYear.id_student.in_(active_students),
                        StudentSectionYear.id_section_year
                        == project.id_section_year,
                        StudentSectionYear.state == ATTENDING,
                    )
                )
            ).all()
            for cursada in cursadas:
                await apply_cursada_transition(self.db, cursada, cursada_state)
