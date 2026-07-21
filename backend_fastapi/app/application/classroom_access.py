"""Small helper module for classroom‑level access checks.

Reused by analytics, export, and classroom API endpoints.
All functions are synchronous and use SQLModel Session directly.
"""

from sqlmodel import Session, select

from app.domain.classroom.models import ClassEnrollment, Classroom


def is_teacher_of_classroom(
    session: Session, teacher_user_id: int, classroom_id: int
) -> bool:
    """Return True when *teacher_user_id* is the teacher of *classroom_id*."""
    classroom = session.get(Classroom, classroom_id)
    return classroom is not None and classroom.teacher_id == teacher_user_id


def is_student_in_classroom(
    session: Session, student_user_id: int, classroom_id: int
) -> bool:
    """Return True when *student_user_id* is enrolled in *classroom_id*."""
    stmt = select(ClassEnrollment).where(
        ClassEnrollment.classroom_id == classroom_id,
        ClassEnrollment.student_id == student_user_id,
    )
    return session.exec(stmt).first() is not None


def can_teacher_access_student(
    session: Session,
    teacher_user_id: int,
    student_user_id: int,
    classroom_id: int | None = None,
) -> bool:
    """Check whether *teacher_user_id* is permitted to view *student_user_id* data.

    When *classroom_id* is given the check is narrow: the teacher must own that
    specific classroom and the student must be enrolled there.  When omitted the
    function scans all classrooms the teacher owns and returns True as soon as
    it finds one where the student is enrolled.
    """
    if classroom_id is not None:
        if not is_teacher_of_classroom(session, teacher_user_id, classroom_id):
            return False
        return is_student_in_classroom(session, student_user_id, classroom_id)

    # No specific classroom – check across all classrooms owned by the teacher.
    teacher_classrooms = session.exec(
        select(Classroom).where(Classroom.teacher_id == teacher_user_id)
    ).all()
    for cls in teacher_classrooms:
        if is_student_in_classroom(session, student_user_id, cls.id):
            return True
    return False


def resolve_student_classroom_ids(
    session: Session, student_user_id: int
) -> list[int]:
    """Return the list of classroom ids the student is enrolled in."""
    enrollments = session.exec(
        select(ClassEnrollment).where(ClassEnrollment.student_id == student_user_id)
    ).all()
    return [e.classroom_id for e in enrollments]
