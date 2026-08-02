"""Structural tests for the MySQL 8.0 DDL migration footguns convention (closes #575).

Acceptance criteria:
- AC1: skills/language-sql/SKILL.md flags ALGORITHM=INPLACE/COPY on ADD COLUMN/DROP COLUMN as a
  suspect override of MySQL 8.0's default ALGORITHM=INSTANT, while confirming the same hint is
  correct and necessary on ADD INDEX/DROP INDEX (INSTANT cannot build an index).
- AC2: the section states BEGIN/COMMIT grants no atomicity over DDL in MySQL — each statement
  auto-commits independently.
- AC3: the section references checking table size (information_schema.tables.table_rows) before
  choosing a migration approach.
- AC4: the section recommends splitting migrations on very large tables (>50M rows) so a partial
  failure leaves a smaller, more legible state.
"""

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent

SQL_SKILL = ROOT / "skills" / "language-sql" / "SKILL.md"

HEADING = "DDL migration footguns (MySQL 8.0)"


def _section(body: str, heading: str) -> str:
    """Extract body of a ## heading, stopping at the next ## heading (skips fenced blocks).

    Returns "" when the heading is absent so callers can assert with their own message.
    """
    marker = f"## {heading}"
    if marker not in body:
        return ""
    start = body.index(marker) + len(marker)
    rest = body[start:]
    fence_open = False
    lines = []
    for line in rest.splitlines():
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~~"):
            fence_open = not fence_open
        if not fence_open and line.startswith("## "):
            break
        lines.append(line)
    return "\n".join(lines)


def test_sql_skill_file_exists():
    assert SQL_SKILL.exists(), "skills/language-sql/SKILL.md must exist"


def test_has_ddl_migration_footguns_section():
    body = SQL_SKILL.read_text()
    section = _section(body, HEADING)
    assert section.strip(), (
        f"skills/language-sql/SKILL.md must contain a non-empty '## {HEADING}' section"
    )


def test_ddl_atomicity_language_and_begin():
    body = SQL_SKILL.read_text()
    section = _section(body, HEADING)
    assert section.strip(), f"'## {HEADING}' section is empty or missing"
    assert "BEGIN" in section, (
        f"'## {HEADING}' must reference BEGIN when explaining DDL auto-commit behavior"
    )
    assert re.search(r"atomic|auto-?commit", section, re.IGNORECASE), (
        f"'## {HEADING}' must state that DDL statements auto-commit independently "
        "(no atomicity from BEGIN/COMMIT)"
    )


def test_add_drop_column_flags_inplace_copy_as_suspect():
    body = SQL_SKILL.read_text()
    section = _section(body, HEADING)
    assert section.strip(), f"'## {HEADING}' section is empty or missing"
    assert "ADD COLUMN" in section, f"'## {HEADING}' must mention ADD COLUMN"
    assert "INSTANT" in section, f"'## {HEADING}' must mention ALGORITHM=INSTANT as the 8.0 default"
    assert re.search(r"INPLACE|COPY", section), (
        f"'## {HEADING}' must call out INPLACE/COPY as overriding the INSTANT default"
    )
    assert re.search(r"overrides?|defect|suspect", section, re.IGNORECASE), (
        f"'## {HEADING}' must characterize an explicit INPLACE/COPY on a column add/drop as "
        "an override/defect, not a neutral fact"
    )
    assert re.search(r"DROP COLUMN.{0,120}8\.0\.29|8\.0\.29.{0,120}DROP COLUMN", section, re.DOTALL), (
        f"'## {HEADING}' must tie DROP COLUMN's INSTANT eligibility specifically to 8.0.29, "
        "distinct from ADD COLUMN's pre-8.0.29 end-of-table-only rule — the ticket's own premise "
        "conflated the two"
    )


def test_add_drop_index_marks_inplace_as_correct():
    body = SQL_SKILL.read_text()
    section = _section(body, HEADING)
    assert section.strip(), f"'## {HEADING}' section is empty or missing"
    assert "INDEX" in section, f"'## {HEADING}' must mention ADD INDEX/DROP INDEX"
    assert "LOCK=NONE" in section, f"'## {HEADING}' must reference LOCK=NONE for index builds"
    assert re.search(r"correct|expected|necessary", section, re.IGNORECASE), (
        f"'## {HEADING}' must state that INPLACE/LOCK=NONE is correct and expected for index "
        "operations, not a blanket ban on INPLACE"
    )


def test_references_table_row_count_check():
    body = SQL_SKILL.read_text()
    section = _section(body, HEADING)
    assert section.strip(), f"'## {HEADING}' section is empty or missing"
    assert "table_rows" in section, (
        f"'## {HEADING}' must reference information_schema.tables.table_rows as a pre-migration check"
    )


def test_references_large_table_migration_split():
    body = SQL_SKILL.read_text()
    section = _section(body, HEADING)
    assert section.strip(), f"'## {HEADING}' section is empty or missing"
    assert "50M" in section, f"'## {HEADING}' must reference the 50M-row threshold"
    assert "split" in section.lower(), (
        f"'## {HEADING}' must recommend splitting migrations on very large tables"
    )


def test_skill_file_stays_within_line_cap():
    body = SQL_SKILL.read_text()
    line_count = len(body.splitlines())
    assert line_count <= 150, (
        f"skills/language-sql/SKILL.md must stay within the 150-line cap "
        f"(scripts/validate.py); currently {line_count} lines"
    )
