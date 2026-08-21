#!/usr/bin/env python3
"""Sync sentinel-delimited shared fragment blocks in agents/*.md against their
shared/agents/*.md source files. Zero dependencies beyond python3 stdlib.

Claude Code never expands `@path` references inside agent, skill, or command
bodies (only in CLAUDE.md memory imports and interactive prompts) — see
issue #619. Instead, a fragment is inlined verbatim between a pair of HTML
comment sentinels:

    <!-- BEGIN shared/agents/lsp.md -->
    …verbatim content of shared/agents/lsp.md…
    <!-- END shared/agents/lsp.md -->

This script keeps that inlined text in sync with its source. It never
creates a new sentinel pair — it only fills or checks pairs an author
already added by hand. A file with zero sentinel pairs is skipped, not an
error.

Usage:
    python3 scripts/sync-shared-blocks.py [--check | --write]

--check (default): report every block whose content has drifted from its
    source, every block whose source file no longer exists, and every BEGIN
    marker with no matching END marker. Exits 1 if anything is out of sync,
    0 otherwise.
--write: rewrite each block's inner content to exactly match its source,
    leaving everything else in the file untouched. Always exits 0, except a
    missing source file (or an unmatched BEGIN marker) still exits 1 — there
    is nothing to fill the block with.
"""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

_SENTINEL_BEGIN_RE = re.compile(r'<!-- BEGIN (shared/agents/[\w-]+\.md) -->\n')


def _iter_sentinel_pairs(text):
    """Yield (name, inner_text, inner_start, inner_stop) for each BEGIN
    marker in *text*, in order of appearance.

    `name` is the shared/agents/<file>.md path named in the marker.
    `inner_text` is the text between the BEGIN and END markers, or None if
    no matching END marker follows the BEGIN (a malformed pair).
    `inner_start`/`inner_stop` are the char offsets bounding inner_text —
    replacing text[inner_start:inner_stop] with fresh content is exactly
    the --write operation. Both are None-safe: inner_stop is None whenever
    inner_text is None.
    """
    for m in _SENTINEL_BEGIN_RE.finditer(text):
        name = m.group(1)
        end_marker = f'<!-- END {name} -->'
        end_idx = text.find(end_marker, m.end())
        if end_idx == -1:
            yield name, None, m.end(), None
            continue
        yield name, text[m.end():end_idx], m.end(), end_idx


def _check(agent_files):
    problems = 0
    for path in agent_files:
        rel = path.relative_to(ROOT)
        text = path.read_text(encoding="utf-8")
        for name, inner, _, _ in _iter_sentinel_pairs(text):
            if inner is None:
                print(f"{rel}: BEGIN {name} has no matching END marker", file=sys.stderr)
                problems += 1
                continue
            source = ROOT / name
            if not source.is_file():
                print(f"{rel}: block for {name} but that source file does not exist", file=sys.stderr)
                problems += 1
                continue
            source_text = source.read_text(encoding="utf-8")
            if inner != source_text:
                print(f"{rel}: block for {name} has drifted from source", file=sys.stderr)
                problems += 1
    if problems:
        print(f"\n{problems} block(s) out of sync.", file=sys.stderr)
        return 1
    print("No drift — all shared blocks in sync.")
    return 0


def _write(agent_files):
    changed = []
    error = False
    for path in agent_files:
        rel = path.relative_to(ROOT)
        text = path.read_text(encoding="utf-8")
        pairs = list(_iter_sentinel_pairs(text))
        if not pairs:
            continue
        new_text = text
        # Apply edits rightmost-first so earlier offsets (computed against
        # the original text) stay valid after each splice.
        for name, inner, inner_start, inner_stop in reversed(pairs):
            if inner is None:
                print(f"{rel}: BEGIN {name} has no matching END marker — skipping", file=sys.stderr)
                error = True
                continue
            source = ROOT / name
            if not source.is_file():
                print(f"{rel}: block for {name} but that source file does not exist — "
                      "cannot fill block", file=sys.stderr)
                error = True
                continue
            source_text = source.read_text(encoding="utf-8")
            if inner == source_text:
                continue
            new_text = new_text[:inner_start] + source_text + new_text[inner_stop:]
        if new_text != text:
            path.write_text(new_text, encoding="utf-8")
            changed.append(str(rel))
    if changed:
        print("Updated:")
        for c in sorted(changed):
            print(f"  {c}")
    else:
        print("Nothing needed changing.")
    return 1 if error else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="report drift (default)")
    mode.add_argument("--write", action="store_true", help="rewrite drifted blocks to match source")
    args = parser.parse_args()

    agent_files = sorted((ROOT / "agents").glob("*.md"))

    if args.write:
        sys.exit(_write(agent_files))
    sys.exit(_check(agent_files))


if __name__ == "__main__":
    main()
