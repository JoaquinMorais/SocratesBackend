import csv
import io
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from config.settings import settings
from models import Attendance, CalendarClass, StudentSectionYear, User
from schemas.attendance_transcript import (
    AttendanceTranscriptReport,
    TranscriptItemPublic,
    TranscriptStudentPublic,
    TranscriptSummaryPublic,
)

# LEGAJO (4-10 dígitos) + separador + nombre. El nombre se corta al próximo legajo.
_LEGAJO_RE = re.compile(
    r"(?<!\d)(\d{4,10})\s*[-–—:,;]\s*([^\n]*?)(?=(?<!\d)\d{4,10}\s*[-–—:,;]|$)"
)
_CHUNK = 1_048_576
_CSV_DELIMITERS = ",;\t"
_STATUSES = (
    "would_create",
    "created",
    "already_present",
    "name_mismatch",
    "not_enrolled",
    "unknown_legajo",
)


@dataclass
class Attempt:
    line: int
    legajo: int | None
    written_name: str | None
    invalid: bool = False
    occurrences: int = 1


@dataclass
class ParsedTranscript:
    lines: int
    ignored_lines: int
    attempts: list[Attempt]


def _too_large() -> HTTPException:
    return HTTPException(
        status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Transcript is too large"
    )


def _empty() -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_ENTITY, "The transcript is empty"
    )


def _no_pairs() -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_ENTITY, "No legajo-name pairs found"
    )


def _invalid_csv() -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid CSV file"
    )


def _forbidden() -> HTTPException:
    return HTTPException(
        status.HTTP_403_FORBIDDEN,
        "Only a professor of this section year or a super admin can do this",
    )


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1")


async def read_transcript_file(file: UploadFile) -> str:
    limit = settings.ATTENDANCE_TRANSCRIPT_MAX_BYTES
    parts = bytearray()
    while chunk := await file.read(_CHUNK):
        parts.extend(chunk)
        if len(parts) > limit:
            raise _too_large()
    if not parts:
        raise _empty()
    return _decode(bytes(parts))


def validate_transcript_text(text: str) -> None:
    if not text.strip():
        raise _empty()
    if len(text.encode("utf-8")) > settings.ATTENDANCE_TRANSCRIPT_MAX_BYTES:
        raise _too_large()


def parse_text(text: str) -> ParsedTranscript:
    lines = text.splitlines()
    attempts: list[Attempt] = []
    ignored = 0
    for line_number, line in enumerate(lines, start=1):
        found = False
        for match in _LEGAJO_RE.finditer(line):
            written_name = match.group(2).strip()
            # Un nombre sin letras (por ejemplo una fecha) es ruido, no un intento.
            if not any(character.isalpha() for character in written_name):
                continue
            found = True
            attempts.append(
                Attempt(
                    line=line_number,
                    legajo=int(match.group(1)),
                    written_name=written_name,
                )
            )
        if not found:
            ignored += 1
    return ParsedTranscript(
        lines=len(lines), ignored_lines=ignored, attempts=attempts
    )


def parse_csv(text: str) -> ParsedTranscript:
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=_CSV_DELIMITERS)
    except csv.Error:
        dialect = csv.excel
    try:
        rows = list(csv.reader(io.StringIO(text), dialect))
    except csv.Error as exc:
        raise _invalid_csv() from exc

    attempts: list[Attempt] = []
    ignored = 0
    header_pending = True
    for row_number, row in enumerate(rows, start=1):
        cells = [cell.strip() for cell in row]
        if not any(cells):
            ignored += 1
            continue
        first = cells[0]
        if header_pending:
            header_pending = False
            if first.lower() == "legajo":
                continue  # encabezado
        if not first:
            ignored += 1
            continue
        if not first.isdigit() or not (4 <= len(first) <= 10):
            attempts.append(
                Attempt(
                    line=row_number,
                    legajo=None,
                    written_name=" ".join(cell for cell in cells if cell) or None,
                    invalid=True,
                )
            )
            continue
        written_name = " ".join(cell for cell in cells[1:] if cell)
        if not written_name:
            attempts.append(
                Attempt(
                    line=row_number,
                    legajo=int(first),
                    written_name=None,
                    invalid=True,
                )
            )
            continue
        attempts.append(
            Attempt(
                line=row_number,
                legajo=int(first),
                written_name=written_name,
            )
        )
    return ParsedTranscript(
        lines=len(rows), ignored_lines=ignored, attempts=attempts
    )


def parse_transcript(text: str, fmt: str) -> ParsedTranscript:
    parsed = parse_csv(text) if fmt == "csv" else parse_text(text)
    if not parsed.attempts:
        raise _no_pairs()
    return parsed


def resolve_format(explicit: str, filename: str | None) -> str:
    if explicit in ("text", "csv"):
        return explicit
    if filename and filename.lower().endswith(".csv"):
        return "csv"
    return "text"


def normalize_name(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    return "".join(
        character
        for character in without_marks.lower()
        if "a" <= character <= "z"
    )


def _name_tokens(value: str) -> list[str]:
    raw = re.split(r"[\s\-]+", value.strip())
    tokens = [normalize_name(token) for token in raw]
    tokens = [token for token in tokens if token]
    meaningful = [token for token in tokens if len(token) >= 3]
    return meaningful or tokens


def _fuzzy_contains(haystack: str, needle: str) -> float:
    """Mejor similitud de `needle` con alguna ventana de `haystack`."""
    if not haystack or not needle:
        return 0.0
    if len(needle) <= 2:
        return 1.0 if needle in haystack else 0.0

    best = 0.0
    smallest = max(1, len(needle) - 2)
    largest = min(len(haystack), len(needle) + 2)
    for size in range(smallest, largest + 1):
        for start in range(0, len(haystack) - size + 1):
            ratio = SequenceMatcher(
                None, haystack[start : start + size], needle
            ).ratio()
            if ratio > best:
                best = ratio
    return best


def _attempt_score(
    written_name: str | None, student: TranscriptStudentPublic
) -> float:
    """Igual que `name_score`, pero con los datos planos del alumno."""
    if not written_name:
        return 0.0
    compact = normalize_name(written_name)
    if not compact:
        return 0.0

    last_tokens = _name_tokens(student.last_name)
    first_tokens = _name_tokens(student.first_name)
    if not last_tokens or not first_tokens:
        return 0.0

    surname = max(_fuzzy_contains(compact, token) for token in last_tokens)
    given = max(_fuzzy_contains(compact, token) for token in first_tokens)
    return min(surname, given)


def _sanitize_file_name(original: str | None) -> str | None:
    if not original:
        return None
    name = original.replace("\\", "/").rsplit("/", 1)[-1].replace("\x00", "")
    name = re.sub(r"\s+", " ", name).strip()
    return name[:255] or None


async def _get_class(db, id_calendar_class: int) -> CalendarClass:
    calendar_class = await db.get(CalendarClass, id_calendar_class)
    if not calendar_class:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Calendar class not found"
        )
    return calendar_class


async def _get_attendance(
    db, id_student_section_year: int, id_calendar_class: int
) -> Attendance | None:
    return (
        await db.exec(
            select(Attendance).where(
                Attendance.id_student_section_year == id_student_section_year,
                Attendance.id_calendar_class == id_calendar_class,
            )
        )
    ).first()


def _empty_summary() -> dict[str, int]:
    return {status: 0 for status in _STATUSES}


async def _import(
    db,
    access,
    id_calendar_class: int,
    parsed: ParsedTranscript,
    *,
    dry_run: bool,
    file_name: str | None,
) -> AttendanceTranscriptReport:
    calendar_class = await _get_class(db, id_calendar_class)
    if not access.can_manage(calendar_class.calendar.id_section_year):
        raise _forbidden()

    rows = (
        await db.exec(
            select(StudentSectionYear, User)
            .join(User, User.id_user == StudentSectionYear.id_student)
            .where(
                StudentSectionYear.id_section_year
                == calendar_class.calendar.id_section_year
            )
        )
    ).all()
    # Datos planos: después de un commit/rollback no dependemos de objetos ORM.
    enrolled: dict[int, tuple[int, TranscriptStudentPublic]] = {
        user.legajo: (
            enrollment.id_student_section_year,
            TranscriptStudentPublic(
                id_student=enrollment.id_student,
                first_name=user.first_name,
                last_name=user.last_name,
                legajo=user.legajo,
            ),
        )
        for enrollment, user in rows
    }

    existing_rows = (
        await db.exec(
            select(Attendance).where(
                Attendance.id_calendar_class == id_calendar_class
            )
        )
    ).all()
    existing = {
        row.id_student_section_year: row.method for row in existing_rows
    }

    groups: dict[int, list[Attempt]] = {}
    invalid_items: list[TranscriptItemPublic] = []
    for attempt in parsed.attempts:
        if attempt.invalid or attempt.legajo is None:
            invalid_items.append(
                TranscriptItemPublic(
                    line=attempt.line,
                    occurrences=1,
                    legajo=attempt.legajo,
                    written_name=attempt.written_name,
                    status="invalid",
                )
            )
            continue
        groups.setdefault(attempt.legajo, []).append(attempt)

    attempted_legajos = set(groups)
    users_with_legajo = set(
        (
            await db.exec(
                select(User.legajo).where(User.legajo.in_(attempted_legajos))
            )
        ).all()
    )

    items: list[TranscriptItemPublic] = []
    counts = _empty_summary()

    for legajo in sorted(
        groups, key=lambda value: min(attempt.line for attempt in groups[value])
    ):
        attempts = groups[legajo]
        occurrences = len(attempts)
        existing_method = None

        if legajo in enrolled:
            enrollment_id, student_public = enrolled[legajo]
            scored = [
                (
                    _attempt_score(attempt.written_name, student_public),
                    attempt,
                )
                for attempt in attempts
            ]
            score, best = max(
                scored, key=lambda pair: (pair[0], -pair[1].line)
            )
            if score < settings.ATTENDANCE_NAME_SIMILARITY:
                status_value = "name_mismatch"
            else:
                existing_method = existing.get(enrollment_id)
                if existing_method is not None:
                    status_value = "already_present"
                elif dry_run:
                    status_value = "would_create"
                else:
                    record = Attendance(
                        id_student_section_year=enrollment_id,
                        id_calendar_class=id_calendar_class,
                        method="transcript",
                    )
                    db.add(record)
                    try:
                        await db.commit()
                        status_value = "created"
                    except IntegrityError:
                        await db.rollback()
                        found = await _get_attendance(
                            db, enrollment_id, id_calendar_class
                        )
                        if found is None:
                            raise
                        status_value = "already_present"
                        existing_method = found.method
            items.append(
                TranscriptItemPublic(
                    line=best.line,
                    occurrences=occurrences,
                    legajo=legajo,
                    written_name=best.written_name,
                    status=status_value,
                    name_score=round(score, 3),
                    student=student_public,
                    existing_method=existing_method,
                )
            )
        elif legajo in users_with_legajo:
            first = min(attempts, key=lambda attempt: attempt.line)
            status_value = "not_enrolled"
            items.append(
                TranscriptItemPublic(
                    line=first.line,
                    occurrences=occurrences,
                    legajo=legajo,
                    written_name=first.written_name,
                    status=status_value,
                )
            )
        else:
            first = min(attempts, key=lambda attempt: attempt.line)
            status_value = "unknown_legajo"
            items.append(
                TranscriptItemPublic(
                    line=first.line,
                    occurrences=occurrences,
                    legajo=legajo,
                    written_name=first.written_name,
                    status=status_value,
                )
            )
        counts[status_value] += 1

    items.extend(invalid_items)
    items.sort(key=lambda item: item.line)

    return AttendanceTranscriptReport(
        dry_run=dry_run,
        file_name=file_name,
        summary=TranscriptSummaryPublic(
            lines=parsed.lines,
            ignored_lines=parsed.ignored_lines,
            attempts=len(parsed.attempts),
            would_create=counts["would_create"],
            created=counts["created"],
            already_present=counts["already_present"],
            name_mismatch=counts["name_mismatch"],
            not_enrolled=counts["not_enrolled"],
            unknown_legajo=counts["unknown_legajo"],
            invalid=len(invalid_items),
        ),
        items=items,
    )


async def import_transcript_from_file(
    db,
    access,
    id_calendar_class: int,
    file: UploadFile,
    *,
    dry_run: bool,
    fmt: str,
) -> AttendanceTranscriptReport:
    text = await read_transcript_file(file)
    parsed = parse_transcript(text, resolve_format(fmt, file.filename))
    return await _import(
        db,
        access,
        id_calendar_class,
        parsed,
        dry_run=dry_run,
        file_name=_sanitize_file_name(file.filename),
    )


async def import_transcript_from_text(
    db,
    access,
    id_calendar_class: int,
    text: str,
    *,
    dry_run: bool,
    fmt: str,
) -> AttendanceTranscriptReport:
    validate_transcript_text(text)
    parsed = parse_transcript(text, fmt)
    return await _import(
        db,
        access,
        id_calendar_class,
        parsed,
        dry_run=dry_run,
        file_name=None,
    )
