from __future__ import annotations

from dataclasses import dataclass

from .model import Document, Member


@dataclass(frozen=True, slots=True)
class MemberProjection:
    text: str
    prefix: str
    projected: bool = True
    reason: str = ""


def _split_lines(text: str):
    return text.splitlines(keepends=True)


def _content_and_ending(line: str):
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith(("\n", "\r")):
        return line[:-1], line[-1:]
    return line, ""


def project_source(source: str) -> MemberProjection:
    """Create a reversible column-zero view of one literal Member source span."""
    lines = _split_lines(source)
    first = next((_content_and_ending(line)[0] for line in lines if _content_and_ending(line)[0].strip()), "")
    prefix = first[: len(first) - len(first.lstrip(" \t"))]
    if not prefix:
        return MemberProjection(source, "")
    projected = []
    for line in lines:
        content, ending = _content_and_ending(line)
        if not content.strip():
            projected.append(ending)
        elif content.startswith(prefix):
            projected.append(content[len(prefix):] + ending)
        else:
            return MemberProjection(source, "", False, "Member lines do not share one exact structural indentation prefix")
    return MemberProjection("".join(projected), prefix)


def project_member(document: Document, member: Member, enabled=True) -> MemberProjection:
    source = document.source(member)
    return project_source(source) if enabled else MemberProjection(source, "", False, "Member dedentation disabled")


def restore_member(projection: MemberProjection, edited_text: str) -> str:
    """Reapply the recorded exact prefix without changing relative indentation."""
    if not projection.projected or not projection.prefix:
        return edited_text
    restored = []
    for line in _split_lines(edited_text):
        content, ending = _content_and_ending(line)
        restored.append((projection.prefix + content if content.strip() else "") + ending)
    return "".join(restored)


def editor_to_file_offset(text: str, offset: int, prefix: str) -> int:
    if not prefix:
        return offset
    offset = max(0, min(offset, len(text)))
    complete_lines = text[:offset].count("\n")
    current_start = text.rfind("\n", 0, offset) + 1
    current_content = text[current_start:offset]
    return offset + len(prefix) * (complete_lines + (1 if current_content.strip() else 0))


def file_to_editor_offset(text: str, offset: int, prefix: str) -> int:
    if not prefix:
        return offset
    # Used after loading a projection; clamp defensively for unusual source.
    lines = text.splitlines(keepends=True)
    consumed_file = consumed_editor = 0
    for line in lines:
        content, ending = _content_and_ending(line)
        file_width = len(content) + len(ending)
        editor_width = len(content[len(prefix):] if content.strip() and content.startswith(prefix) else content) + len(ending)
        if offset <= consumed_file + file_width:
            local = offset - consumed_file
            if content.strip() and content.startswith(prefix):
                local = max(0, local - len(prefix))
            return consumed_editor + min(local, editor_width)
        consumed_file += file_width
        consumed_editor += editor_width
    return consumed_editor
