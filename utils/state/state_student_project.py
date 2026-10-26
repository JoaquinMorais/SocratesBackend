from sqlmodel import col, select

from models import Status, StudentProject
from models.state.state_student_project import (
    Active,
    PendingApprovalMember,
    RejectedMember,
)
from utils.statuses import get_status


class MembershipEffector:
    """Aplica en la BD los efectos de entrar a un estado de membresía."""

    def __init__(self, db):
        self.db = db

    async def reject_other_pending(self, membership) -> None:
        """Al ser `member`, las otras solicitudes pendientes del alumno se rechazan."""
        conditions = [
            StudentProject.id_student == membership.id_student,
            Status.ambito == "student_project",
            Status.code == PendingApprovalMember.code,
        ]
        if membership.id_student_project is not None:
            conditions.append(
                StudentProject.id_student_project != membership.id_student_project
            )
        rows = (
            await self.db.exec(
                select(StudentProject)
                .join(Status, Status.id_status == StudentProject.id_status)
                .where(*conditions)
            )
        ).all()
        if not rows:
            return

        rejected = await get_status(self.db, "student_project", RejectedMember.code)
        for other in rows:
            other.status = rejected
            other.is_leader = False
            self.db.add(other)

    async def promote_successor(self, membership) -> None:
        """Si el que deja el grupo era jefe, asciende al `active` más antiguo."""
        if not membership.is_leader:
            return

        membership.is_leader = False
        self.db.add(membership)
        await self.db.flush()  # libera el índice único de jefe antes de promover

        successor = await self._oldest_active(
            membership.id_project, exclude_id=membership.id_student_project
        )
        if successor is not None:
            successor.is_leader = True
            self.db.add(successor)

    async def _oldest_active(
        self, id_project: int, exclude_id: int | None = None
    ) -> StudentProject | None:
        conditions = [
            StudentProject.id_project == id_project,
            Status.ambito == "student_project",
            Status.code == Active.code,
        ]
        if exclude_id is not None:
            conditions.append(StudentProject.id_student_project != exclude_id)
        return (
            await self.db.exec(
                select(StudentProject)
                .join(Status, Status.id_status == StudentProject.id_status)
                .where(*conditions)
                .order_by(
                    col(StudentProject.enrolled_at),
                    col(StudentProject.id_student_project),
                )
                .limit(1)
            )
        ).first()
