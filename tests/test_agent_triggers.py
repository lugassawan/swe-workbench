"""Smoke harness: each agent's dispatch-prompt fixtures must rank that agent #1
by BM25 against all 22 agent descriptions, and every agent description must
retain enough vocabulary that no two agents blur together. Catches description
drift that would prevent auto-dispatch or collapse two agents' routing signal.

Fixture prompts (tests/fixtures/agent_triggers/<agent>.txt) are authored from
each agent's body "Reachable via" dispatch site and its stated scope/boundary
sections — never from its description — so a description regression can
actually fail these tests instead of trivially matching itself.

Run locally:   pytest tests/test_agent_triggers.py -v
"""

from pathlib import Path

import pytest

from test_skill_triggers import _build_bm25_index, _rank_skills, _tokenize

ROOT = Path(__file__).parent.parent
_AGENTS_DIR = ROOT / "agents"
_AGENT_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "agent_triggers"


# ── Corpus / fixture loaders ───────────────────────────────────────────────

def _load_agent_corpus(agents_dir: Path) -> dict[str, list[str]]:
    """Return {agent_name: [tokens]} from each agents/*.md description field."""
    from validate import parse_frontmatter, _parse_description  # already on sys.path via conftest

    corpus: dict[str, list[str]] = {}
    for agent_md in sorted(agents_dir.glob("*.md")):
        fm = parse_frontmatter(agent_md)
        if fm and "description" in fm:
            description = _parse_description(fm["description"])
            if description:
                corpus[agent_md.stem] = _tokenize(description)
    return corpus


def _collect_agent_fixtures(fixtures_dir: Path) -> list[tuple[str, str]]:
    """Return [(agent_name, prompt)] from tests/fixtures/agent_triggers/*.txt."""
    fixtures: list[tuple[str, str]] = []
    for triggers_txt in sorted(fixtures_dir.glob("*.txt")):
        agent_name = triggers_txt.stem
        for line in triggers_txt.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                fixtures.append((agent_name, stripped))
    return fixtures


# ── Module-scope fixtures (load real agents once per session) ─────────────

@pytest.fixture(scope="module")
def real_agent_corpus():
    return _load_agent_corpus(_AGENTS_DIR)


@pytest.fixture(scope="module")
def real_agent_index(real_agent_corpus):
    return _build_bm25_index(real_agent_corpus)


# ── Parametrized harness ───────────────────────────────────────────────────

_AGENT_FIXTURES = _collect_agent_fixtures(_AGENT_FIXTURES_DIR)
assert _AGENT_FIXTURES, (
    f"No agent trigger fixtures found under {_AGENT_FIXTURES_DIR} — "
    "check that tests/fixtures/agent_triggers/*.txt files exist"
)

# Every agents/*.md must have a matching fixture file — otherwise a new
# agent silently gets zero coverage from this whole harness instead of a
# loud failure here.
_agents_on_disk = {p.stem for p in _AGENTS_DIR.glob("*.md")}
_agents_with_fixtures = {name for name, _ in _AGENT_FIXTURES}
_MISSING_AGENT_FIXTURES = _agents_on_disk - _agents_with_fixtures
assert not _MISSING_AGENT_FIXTURES, (
    f"agents/*.md with no tests/fixtures/agent_triggers/<name>.txt: "
    f"{sorted(_MISSING_AGENT_FIXTURES)}"
)

# Minimum BM25 score gap between #1 and #2 when the target agent ranks top.
# Reuses the same value skills use (tests/test_skill_triggers.py's
# _SCORE_MARGIN) rather than defining an independent constant, since it is
# the same BM25 scorer and the same drift risk — not imported directly
# because that name is module-private to test_skill_triggers and this file
# intentionally keeps its own copy so the two suites can diverge later
# without silently coupling.
_SCORE_MARGIN = 0.1


@pytest.mark.parametrize(
    "agent_name,prompt",
    _AGENT_FIXTURES,
    ids=[f"{a}::{p[:50]}" for a, p in _AGENT_FIXTURES],
)
def test_prompt_ranks_target_agent_top1(agent_name, prompt, real_agent_corpus, real_agent_index):
    ranked = _rank_skills(prompt, real_agent_corpus, real_agent_index)
    top3_summary = ", ".join(f"`{n}` ({sc:.2f})" for n, sc in ranked[:3])
    target_rank = next((i for i, (n, _) in enumerate(ranked) if n == agent_name), None)
    assert target_rank is not None, f"agent `{agent_name}` not found in corpus"

    assert target_rank == 0, (
        f"prompt for `{agent_name}` ranked #{target_rank + 1}; top-3: [{top3_summary}]. "
        f"Refine agents/{agent_name}.md description."
    )

    target_score = ranked[0][1]
    if len(ranked) > 1:
        margin = target_score - ranked[1][1]
        assert margin >= _SCORE_MARGIN, (
            f"prompt for `{agent_name}` ranks #1 but margin over `{ranked[1][0]}` is only "
            f"{margin:.3f} (< {_SCORE_MARGIN}). Top-3: [{top3_summary}]. "
            f"IDF drift may flip this ranking — tighten the description or raise _SCORE_MARGIN."
        )


# ── Distinctiveness ratchet ─────────────────────────────────────────────

# Every agent description must retain at least this many tokens that appear
# in no other agent's description. Measured against the live corpus at
# authoring time (before agent-description compression): min 6
# (test-reviewer), max 42 (product-manager). This is a hard floor compression
# must never cross — it is what catches "two agents blurred together" even
# when both still individually rank #1 for their own fixtures.
_MIN_UNIQUE_TOKENS = 6


def _unique_token_counts(corpus: dict[str, list[str]]) -> dict[str, int]:
    token_sets = {name: set(tokens) for name, tokens in corpus.items()}
    counts = {}
    for name, own in token_sets.items():
        others = set()
        for other_name, other_tokens in token_sets.items():
            if other_name != name:
                others |= other_tokens
        counts[name] = len(own - others)
    return counts


def test_agent_distinctiveness_ratchet(real_agent_corpus):
    """Print a sorted unique-token-count table and fail any agent below
    _MIN_UNIQUE_TOKENS — the signal that compression blurred two agents
    together even though each still ranks #1 for its own fixtures.
    """
    counts = _unique_token_counts(real_agent_corpus)
    ordered = sorted(counts.items(), key=lambda kv: kv[1])
    table = "\n".join(f"  {count:3d}  {name}" for name, count in ordered)
    print(f"\nagent distinctiveness report (unique tokens, ascending):\n{table}")

    below_floor = [(n, c) for n, c in ordered if c < _MIN_UNIQUE_TOKENS]
    assert not below_floor, (
        f"agent(s) below the {_MIN_UNIQUE_TOKENS}-unique-token floor: {below_floor}. "
        "Two agent descriptions have blurred together — widen the description "
        "for the affected agent(s) rather than lowering _MIN_UNIQUE_TOKENS."
    )
