from __future__ import annotations

import re
from difflib import SequenceMatcher

from .models import SectionDefinition, SectionRecord


HEADING_MAX_WORDS = 12
MATCH_THRESHOLD = 0.72


def normalize_text(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def heading_candidates(page_text: str) -> list[tuple[str, int]]:
    lines = [line.strip() for line in page_text.splitlines() if line.strip()]
    candidates: list[tuple[str, int]] = []
    for idx, line in enumerate(lines):
        clean = line.strip(":- ")
        words = clean.split()
        if not clean or len(words) > HEADING_MAX_WORDS:
            continue
        uppercaseish = clean.upper() == clean and any(ch.isalpha() for ch in clean)
        numbered = bool(re.match(r"^(\d+\.|[IVX]+\.)\s+", clean, flags=re.I))
        titleish = clean.istitle()
        keywordish = any(token in normalize_text(clean) for token in ["analysis", "summary", "risk", "collateral", "covenant", "repayment", "financial"])
        if uppercaseish or numbered or titleish or keywordish:
            candidates.append((clean, idx))
    return candidates


def match_section(header: str, definitions: list[SectionDefinition]) -> SectionDefinition | None:
    normalized = normalize_text(header)
    best_score = 0.0
    best: SectionDefinition | None = None
    for definition in definitions:
        names = [definition.display_name, definition.section_id.replace("_", " "), *definition.aliases]
        for name in names:
            score = SequenceMatcher(None, normalized, normalize_text(name)).ratio()
            if normalize_text(name) in normalized or normalized in normalize_text(name):
                score = max(score, 0.92)
            if score > best_score:
                best_score = score
                best = definition
    if best_score >= MATCH_THRESHOLD:
        return best
    return None


def _slice_section_text(
    page_lines: dict[int, list[str]],
    start_page: int,
    start_line: int,
    end_page: int,
    end_line: int | None,
) -> str:
    chunks: list[str] = []
    for page_number in range(start_page, end_page + 1):
        lines = page_lines.get(page_number, [])
        if page_number == start_page and page_number == end_page:
            chunks.extend(lines[start_line:end_line])
        elif page_number == start_page:
            chunks.extend(lines[start_line:])
        elif page_number == end_page and end_line is not None:
            chunks.extend(lines[:end_line])
        else:
            chunks.extend(lines)
    return "\n".join(line for line in chunks if line.strip()).strip()


def propose_sections(
    memo_id: str,
    pages: list[dict],
    definitions: list[SectionDefinition],
    extraction_method: str,
) -> list[SectionRecord]:
    found: list[tuple[int, int, str, SectionDefinition | None]] = []
    page_lines: dict[int, list[str]] = {}
    for page in pages:
        text = page.get("text", "")
        page_number = int(page["page_number"])
        page_lines[page_number] = text.splitlines()
        for header, line_idx in heading_candidates(text):
            match = match_section(header, definitions)
            if match:
                found.append((page_number, line_idx, header, match))

    seen = set()
    ordered_found: list[tuple[int, int, str, SectionDefinition]] = []
    for page_number, line_idx, header, definition in sorted(found, key=lambda item: (item[0], item[1])):
        assert definition is not None
        key = (page_number, definition.section_id, header.lower())
        if key not in seen:
            ordered_found.append((page_number, line_idx, header, definition))
            seen.add(key)

    if not ordered_found:
        full_text = "\n\n".join(page.get("text", "") for page in pages)
        first_definition = sorted(definitions, key=lambda section: section.display_order)[0]
        return [
            SectionRecord(
                section_id="section_001",
                memo_id=memo_id,
                canonical_section_id=first_definition.section_id,
                canonical_section_name=first_definition.display_name,
                original_header="Full memo text",
                page_start=1,
                page_end=max([int(page.get("page_number", 1)) for page in pages], default=1),
                text=full_text,
                extraction_method=extraction_method,  # type: ignore[arg-type]
                reviewer_confirmed=False,
            )
        ]

    sections: list[SectionRecord] = []
    max_page = max(page_lines.keys(), default=1)
    for idx, (page_number, line_idx, header, definition) in enumerate(ordered_found, start=1):
        if idx < len(ordered_found):
            next_page, next_line_idx = ordered_found[idx][0], ordered_found[idx][1]
            page_end = next_page
            section_text = _slice_section_text(page_lines, page_number, line_idx, next_page, next_line_idx)
        else:
            page_end = max_page
            section_text = _slice_section_text(page_lines, page_number, line_idx, max_page, None)
        sections.append(
            SectionRecord(
                section_id=f"section_{idx:03}",
                memo_id=memo_id,
                canonical_section_id=definition.section_id,
                canonical_section_name=definition.display_name,
                original_header=header,
                page_start=page_number,
                page_end=page_end,
                text=section_text,
                extraction_method=extraction_method,  # type: ignore[arg-type]
                reviewer_confirmed=False,
            )
        )
    return sections


def required_section_gaps(
    sections: list[dict],
    definitions: list[SectionDefinition],
    memo_type: str,
    facility_type: str,
) -> list[SectionDefinition]:
    present = {section.get("canonical_section_id") for section in sections}
    gaps: list[SectionDefinition] = []
    for definition in definitions:
        memo_match = not definition.memo_types or memo_type in definition.memo_types
        facility_match = not definition.facility_types or facility_type in definition.facility_types
        if definition.required and memo_match and facility_match and definition.section_id not in present:
            gaps.append(definition)
    return gaps
