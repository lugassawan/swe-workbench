#!/usr/bin/env python3
"""Compress skill/agent description: frontmatter against the BM25 trigger-fixture suite.

Every Claude Code / Pi session pays for the catalog's description: frontmatter before
the user types anything (#680). This is a global optimizer, not a per-file editor:
descriptions share one BM25 corpus and one avg_dl, so shortening any one description
perturbs the ranking of all others. It never reimplements BM25 — it imports the scorer
and the fixture harness directly from tests/test_skill_triggers.py (and, once it
exists, tests/test_agent_triggers.py) so it optimizes against exactly what CI enforces.

Clause model: each description is split on top-level (paren-aware) ", " / "; "
separators into an ordered list of clauses. Clause 0 (the lead clause) is anchored and
never dropped. The optimizer orders every other clause across the whole corpus
longest-first, trial-drops one, rebuilds the BM25 index, and re-evaluates every
fixture; it accepts the drop only if the full suite stays green, otherwise restores
the clause. This repeats to a fixed point (a full pass with zero accepted drops).

This is a *monotone shrink*: a clause, once dropped, is never re-added and no clause
is ever lengthened. That is what keeps the loop convergent — see #680's plan for why
a per-token filter with greedy repair does not have this property.

The optimizer maximises BM25 pass-rate; it does not know which words a human reader
still needs (file extensions, manifest names, product names). --apply always requires
a hand review of the diff before it is trustworthy — see #680 commit 2/4.

Modes:
  --report    Measure current corpus size + print a per-item worst-margin table. Read-only. Default.
  --dry-run   Run the optimizer in memory and print the proposed unified diff. Nothing written.
  --apply     Run the optimizer and rewrite description: lines in place.
  --agents    Target agents/*.md instead of skills/*/SKILL.md (requires tests/test_agent_triggers.py).

Usage:
  python3 scripts/compress-descriptions.py --report
  python3 scripts/compress-descriptions.py --dry-run
  python3 scripts/compress-descriptions.py --apply
  python3 scripts/compress-descriptions.py --agents --apply
"""

import argparse
import difflib
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import validate  # noqa: E402
from validate import parse_frontmatter, _parse_description  # noqa: E402
import test_skill_triggers as skill_harness  # noqa: E402


# ── UTF-16 char counting (matches validate.py's PI_SKILL_DESCRIPTION_CAP measurement) ──

def _utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


# ── Frontmatter description-line location/replacement ──────────────────────

def _frontmatter_bounds(text: str):
    """Return (start, end) offsets of the frontmatter block body (between the
    opening '---' and closing '---' delimiters), or None. Mirrors
    validate.parse_frontmatter's own block-boundary logic exactly."""
    if not text.startswith("---"):
        return None
    end = text.find("\n---\n", 3)
    if end == -1:
        end = text.find("\n---", 3)
    if end == -1:
        return None
    return 3, end


_DESC_LINE_RE = validate.re.compile(r"^(description:[ \t]*)(.*)$", validate.re.MULTILINE)


def _replace_description_value(text: str, new_raw_value: str) -> str:
    """Replace only the value portion of the frontmatter 'description:' line,
    scoped to the frontmatter block so a body-text line starting with
    'description:' can never be matched."""
    bounds = _frontmatter_bounds(text)
    if bounds is None:
        raise ValueError("no frontmatter block")
    start, end = bounds
    block = text[start:end]
    m = _DESC_LINE_RE.search(block)
    if m is None:
        raise ValueError("no 'description:' line in frontmatter block")
    new_block = block[: m.start(2)] + new_raw_value + block[m.end(2) :]
    return text[:start] + new_block + text[end:]


def _serialize_value(new_text: str, original_raw_value: str) -> str:
    """Re-emit new_text in the same YAML scalar style the original value used."""
    if original_raw_value.startswith('"'):
        escaped = new_text.replace("\\", "\\\\").replace('"', '\\"')
        serialized = '"' + escaped + '"'
        # Only \\ and " are re-escaped above; assert the round-trip explicitly
        # rather than silently write a line that would decode to something
        # other than new_text — relevant if a future description ever needs
        # one of the other escapes validate._parse_double_quoted_description
        # decodes (e.g. \n, \uXXXX), which this function does not re-encode.
        decoded = validate._parse_double_quoted_description(serialized)
        assert decoded == new_text, (
            f"double-quote re-serialization round-trip mismatch: {decoded!r} != {new_text!r}"
        )
        return serialized
    if original_raw_value.startswith("'"):
        return "'" + new_text.replace("'", "''") + "'"
    # Plain scalar — verify it still round-trips as plain (a merged clause
    # boundary could accidentally produce a ": " sequence or similar); fall
    # back to double-quoting rather than emit an unparseable frontmatter line.
    if validate._parse_plain_description(new_text) == new_text:
        return new_text
    escaped = new_text.replace("\\", "\\\\").replace('"', '\\"')
    return '"' + escaped + '"'


# ── Clause model ─────────────────────────────────────────────────────────

def _split_clauses(description: str):
    """Split on top-level (paren/bracket-aware) ', ' or '; '. Returns
    (clauses, seps) where len(seps) == len(clauses) - 1 and
    clauses[0] + ''.join(s + c for s, c in zip(seps, clauses[1:])) == description."""
    depth = 0
    n = len(description)
    i = 0
    start = 0
    clauses = []
    seps = []
    while i < n:
        ch = description[i]
        if ch in "([":
            depth += 1
            i += 1
            continue
        if ch in ")]":
            depth = max(depth - 1, 0)
            i += 1
            continue
        if depth == 0 and description[i : i + 2] in (", ", "; "):
            clauses.append(description[start:i])
            seps.append(description[i : i + 2])
            start = i + 2
            i += 2
            continue
        i += 1
    clauses.append(description[start:])
    return clauses, seps


class DescriptionFile:
    """One skill's or agent's description:, split into anchored clauses."""

    def __init__(self, path: Path, name: str):
        self.path = path
        self.name = name
        self.text = path.read_text(encoding="utf-8")
        fm = parse_frontmatter(path, text=self.text)
        self.raw_value = fm.get("description") if fm else None
        self.original_description = (
            _parse_description(self.raw_value) if self.raw_value is not None else None
        )
        if self.original_description is None:
            self.clauses, self.seps = [], []
        else:
            self.clauses, self.seps = _split_clauses(self.original_description)
            rebuilt = self.render()
            if rebuilt != self.original_description:
                raise AssertionError(
                    f"{path}: clause round-trip mismatch\n  original: {self.original_description!r}\n  rebuilt:  {rebuilt!r}"
                )

    def render(self) -> str:
        if not self.clauses:
            return self.original_description or ""
        parts = [self.clauses[0]]
        for sep, clause in zip(self.seps, self.clauses[1:]):
            parts.append(sep)
            parts.append(clause)
        return "".join(parts)

    def drop(self, pos: int):
        """Remove the clause at list position pos (pos >= 1). Returns undo state."""
        clause = self.clauses.pop(pos)
        sep = self.seps.pop(pos - 1)
        return pos, sep, clause

    def restore(self, undo) -> None:
        pos, sep, clause = undo
        self.clauses.insert(pos, clause)
        self.seps.insert(pos - 1, sep)

    def dirty(self) -> bool:
        return self.render() != self.original_description

    def write(self) -> None:
        new_value = _serialize_value(self.render(), self.raw_value)
        new_text = _replace_description_value(self.text, new_value)
        self.path.write_text(new_text, encoding="utf-8")


# ── Skill-corpus adapter ─────────────────────────────────────────────────

def _load_skill_files():
    files = {}
    for skill_md in sorted((ROOT / "skills").glob("*/SKILL.md")):
        df = DescriptionFile(skill_md, skill_md.parent.name)
        if df.original_description is not None:
            files[df.name] = df
    return files


def _tokens_corpus(files):
    return {name: skill_harness._tokenize(df.render()) for name, df in files.items()}


def _siblings_of(name, sibling_sets):
    groups = [s for s in sibling_sets if name in s]
    return set().union(*groups) if groups else {name}


def _skill_fixture_passes(skill_name, prompt, corpus, index, sibling_sets):
    ranked = skill_harness._rank_skills(prompt, corpus, index)
    names = [n for n, _ in ranked]
    if skill_name not in names:
        return False
    target_rank = names.index(skill_name)
    my_sibs = _siblings_of(skill_name, sibling_sets)
    if target_rank == 0:
        target_score = ranked[0][1]
        non_sibs_below = [(n, sc) for n, sc in ranked[1:] if n not in my_sibs]
        if not non_sibs_below:
            return True
        margin = target_score - non_sibs_below[0][1]
        return margin >= skill_harness._SCORE_MARGIN
    outrankers = names[:target_rank]
    return all(n in my_sibs for n in outrankers)


def _family_fixture_passes(skill_name, prompt, corpus, index, sibling_sets):
    ranked = skill_harness._rank_skills(prompt, corpus, index)
    scores = dict(ranked)
    target_score = scores[skill_name]
    my_sibs = _siblings_of(skill_name, sibling_sets)
    rivals = [
        sc
        for n, sc in ranked
        if n != skill_name and n.startswith("workflow-") and n not in my_sibs
    ]
    if not rivals:
        return True
    return (target_score - max(rivals)) >= skill_harness._FAMILY_MARGIN


def _make_skill_suite_passes(fixtures, sibling_sets):
    def _passes(files, changed_name=None):
        corpus = _tokens_corpus(files)
        index = skill_harness._build_bm25_index(corpus)
        ordered = fixtures
        if changed_name is not None:
            own = [f for f in fixtures if f[0] == changed_name]
            rest = [f for f in fixtures if f[0] != changed_name]
            ordered = own + rest
        for skill_name, prompt in ordered:
            if not _skill_fixture_passes(skill_name, prompt, corpus, index, sibling_sets):
                return False
        for skill_name, prompt in fixtures:
            if skill_name.startswith("workflow-") and not _family_fixture_passes(
                skill_name, prompt, corpus, index, sibling_sets
            ):
                return False
        # Also gate on the corpus-wide margin-report ratchet
        # (test_self_rank_margin_report's _MEASURED_MIN_MARGIN) — without
        # this, the optimizer could accept a sequence of drops that stays
        # green against the top-1/family checks above yet fails that test
        # once actually run. Mirrors _make_agent_suite_passes() folding in
        # _distinctiveness_passes() for the same reason.
        worst_margins = skill_harness._self_rank_worst_margins(corpus, index, fixtures, sibling_sets)
        if worst_margins and min(worst_margins.values()) < skill_harness._MEASURED_MIN_MARGIN:
            return False
        return True

    return _passes


def _skill_margin_table(files, fixtures, sibling_sets):
    corpus = _tokens_corpus(files)
    index = skill_harness._build_bm25_index(corpus)
    worst = {}
    for skill_name, prompt in fixtures:
        ranked = skill_harness._rank_skills(prompt, corpus, index)
        scores = dict(ranked)
        target_score = scores[skill_name]
        my_sibs = _siblings_of(skill_name, sibling_sets)
        non_sib_scores = [sc for n, sc in ranked if n not in my_sibs]
        best_non_sib = max(non_sib_scores) if non_sib_scores else 0.0
        margin = target_score - best_non_sib
        worst[skill_name] = min(worst.get(skill_name, margin), margin)
    return worst


# ── Agent-corpus adapter (requires tests/test_agent_triggers.py, added #680 commit 3) ──

def _load_agent_module():
    import test_agent_triggers as agent_harness

    return agent_harness


def _load_agent_files(agent_harness):
    files = {}
    for agent_md in sorted((ROOT / "agents").glob("*.md")):
        df = DescriptionFile(agent_md, agent_md.stem)
        if df.original_description is not None:
            files[df.name] = df
    return files


def _agent_fixture_passes(agent_harness, agent_name, prompt, corpus, index):
    ranked = agent_harness._rank_skills(prompt, corpus, index)
    names = [n for n, _ in ranked]
    if agent_name not in names or names[0] != agent_name:
        return False
    if len(ranked) < 2:
        return True
    margin = ranked[0][1] - ranked[1][1]
    return margin >= agent_harness._SCORE_MARGIN


def _distinctiveness_passes(agent_harness, corpus):
    all_tokens = {name: set(tokens) for name, tokens in corpus.items()}
    for name, own in all_tokens.items():
        others = set()
        for n2, t2 in all_tokens.items():
            if n2 != name:
                others |= t2
        if len(own - others) < agent_harness._MIN_UNIQUE_TOKENS:
            return False
    return True


def _make_agent_suite_passes(agent_harness, fixtures):
    def _passes(files, changed_name=None):
        corpus = _tokens_corpus(files)
        if not _distinctiveness_passes(agent_harness, corpus):
            return False
        index = agent_harness._build_bm25_index(corpus)
        ordered = fixtures
        if changed_name is not None:
            own = [f for f in fixtures if f[0] == changed_name]
            rest = [f for f in fixtures if f[0] != changed_name]
            ordered = own + rest
        for agent_name, prompt in ordered:
            if not _agent_fixture_passes(agent_harness, agent_name, prompt, corpus, index):
                return False
        return True

    return _passes


def _agent_margin_table(agent_harness, files, fixtures):
    corpus = _tokens_corpus(files)
    index = agent_harness._build_bm25_index(corpus)
    worst = {}
    for agent_name, prompt in fixtures:
        ranked = agent_harness._rank_skills(prompt, corpus, index)
        scores = dict(ranked)
        target_score = scores[agent_name]
        rest = [sc for n, sc in ranked if n != agent_name]
        best_rest = max(rest) if rest else 0.0
        margin = target_score - best_rest
        worst[agent_name] = min(worst.get(agent_name, margin), margin)
    return worst


# ── Optimizer ────────────────────────────────────────────────────────────

def _optimize(files, suite_passes_fn, log=lambda *a: None):
    """Monotone-shrink global optimizer: longest-clause-first, full-suite
    re-evaluation, accept only on a fully green suite. Repeats to a fixed
    point. Position-based candidate indices go stale within a single pass
    when an earlier same-file drop shifts later indices — both the
    out-of-range case (pos no longer exists) and the in-range-but-wrong-
    clause case (pos now names a neighbor that shifted into that slot) are
    guarded by re-checking the recorded length against the clause actually
    at pos before trial-dropping it, so a stale candidate is skipped rather
    than silently dropping a different clause than the one its place in the
    longest-first sort order was earned by. Skipped candidates are retried
    next pass against a freshly rebuilt candidate list; the loop runs to a
    fixed point (zero accepted drops in a full pass)."""
    total_dropped = 0
    pass_num = 0
    while True:
        pass_num += 1
        candidates = [
            (len(df.clauses[pos]), name, pos)
            for name, df in files.items()
            for pos in range(1, len(df.clauses))
        ]
        if not candidates:
            break
        candidates.sort(key=lambda c: -c[0])
        accepted_this_pass = 0
        for expected_len, name, pos in candidates:
            df = files[name]
            if pos >= len(df.clauses) or len(df.clauses[pos]) != expected_len:
                continue
            undo = df.drop(pos)
            if suite_passes_fn(files, changed_name=name):
                total_dropped += 1
                accepted_this_pass += 1
            else:
                df.restore(undo)
        log(f"pass {pass_num}: {accepted_this_pass} clause(s) dropped")
        if accepted_this_pass == 0:
            break
    return total_dropped


# ── CLI ──────────────────────────────────────────────────────────────────

def _print_margin_table(title, worst):
    print(f"\n{title} (worst margin per item, ascending):")
    for name, margin in sorted(worst.items(), key=lambda kv: kv[1])[:20]:
        print(f"  {margin:8.4f}  {name}")
    print(f"  corpus-wide minimum: {min(worst.values()):.4f}" if worst else "  (no fixtures)")


def _report_skills():
    files = _load_skill_files()
    fixtures = skill_harness._collect_fixtures(skill_harness._SKILLS_DIR)
    sibling_sets = skill_harness._load_sibling_sets(skill_harness._SIBLING_SETS_FILE)
    total_chars = sum(_utf16_len(df.render()) for df in files.values())
    print(f"skills: {len(files)} descriptions, {total_chars} chars ({len(fixtures)} fixtures)")
    worst = _skill_margin_table(files, fixtures, sibling_sets)
    _print_margin_table("skills", worst)


def _report_agents():
    agent_harness = _load_agent_module()
    files = _load_agent_files(agent_harness)
    fixtures = agent_harness._collect_agent_fixtures(agent_harness._AGENT_FIXTURES_DIR)
    total_chars = sum(_utf16_len(df.render()) for df in files.values())
    print(f"agents: {len(files)} descriptions, {total_chars} chars ({len(fixtures)} fixtures)")
    worst = _agent_margin_table(agent_harness, files, fixtures)
    _print_margin_table("agents", worst)


def _run_optimizer_skills():
    files = _load_skill_files()
    fixtures = skill_harness._collect_fixtures(skill_harness._SKILLS_DIR)
    sibling_sets = skill_harness._load_sibling_sets(skill_harness._SIBLING_SETS_FILE)
    before = sum(_utf16_len(df.render()) for df in files.values())
    suite_passes = _make_skill_suite_passes(fixtures, sibling_sets)
    assert suite_passes(files), "baseline suite does not pass before optimizing — aborting"
    dropped = _optimize(files, suite_passes, log=print)
    after = sum(_utf16_len(df.render()) for df in files.values())
    print(f"skills: {before} -> {after} chars ({dropped} clauses dropped)")
    return files


def _run_optimizer_agents():
    agent_harness = _load_agent_module()
    files = _load_agent_files(agent_harness)
    fixtures = agent_harness._collect_agent_fixtures(agent_harness._AGENT_FIXTURES_DIR)
    before = sum(_utf16_len(df.render()) for df in files.values())
    suite_passes = _make_agent_suite_passes(agent_harness, fixtures)
    assert suite_passes(files), "baseline suite does not pass before optimizing — aborting"
    dropped = _optimize(files, suite_passes, log=print)
    after = sum(_utf16_len(df.render()) for df in files.values())
    print(f"agents: {before} -> {after} chars ({dropped} clauses dropped)")
    return files


def _print_diff(files):
    for name in sorted(files):
        df = files[name]
        if not df.dirty():
            continue
        # Diff the actual serialized value --apply would write, not the bare
        # description text — a drop that trips the plain-scalar-safety
        # fallback (switching an unquoted description to quoted) must be
        # visible in --dry-run output before --apply writes it.
        after_value = _serialize_value(df.render(), df.raw_value)
        diff = difflib.unified_diff(
            [df.raw_value + "\n"],
            [after_value + "\n"],
            fromfile=f"{name} (before)",
            tofile=f"{name} (after)",
        )
        sys.stdout.writelines(diff)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--agents", action="store_true", help="Target agents/*.md instead of skills/*/SKILL.md")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--report", action="store_true", help="Measure + margin table, read-only (default)")
    mode.add_argument("--dry-run", action="store_true", help="Run the optimizer, print the diff, write nothing")
    mode.add_argument("--apply", action="store_true", help="Run the optimizer and rewrite description: lines")
    args = parser.parse_args()

    if not (args.dry_run or args.apply):
        args.report = True

    if args.report:
        (_report_agents if args.agents else _report_skills)()
        return

    files = (_run_optimizer_agents if args.agents else _run_optimizer_skills)()

    if args.dry_run:
        _print_diff(files)
        return

    for df in files.values():
        if df.dirty():
            df.write()
    changed = sum(1 for df in files.values() if df.dirty())
    print(f"wrote {changed} file(s)")


if __name__ == "__main__":
    main()
