"""Smoke harness: each skill's triggers.txt prompts must rank that skill #1
(or within its documented sibling set) by BM25 against all 22 skill
descriptions. Catches description drift that would prevent auto-trigger.

Run locally:   pytest tests/test_skill_triggers.py -v
Nightly CI:    .github/workflows/skill-triggers.yml
"""

import math
import re
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
_SKILLS_DIR = ROOT / "skills"
_SIBLING_SETS_FILE = Path(__file__).parent / "skill_sibling_sets.txt"

_TOKEN_RE = re.compile(r"[a-z0-9]+")


# ── BM25 (pure stdlib, ~50 lines) ─────────────────────────────────────────

def _tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if len(t) > 1]


def _build_bm25_index(
    corpus: dict[str, list[str]], k1: float = 1.5, b: float = 0.75
) -> dict:
    N = len(corpus)
    avg_dl = sum(len(t) for t in corpus.values()) / max(N, 1)
    df: dict[str, int] = {}
    for tokens in corpus.values():
        for t in set(tokens):
            df[t] = df.get(t, 0) + 1
    # Lucene BM25 variant — log argument is always ≥ 1, so IDF is always ≥ 0.
    idf = {
        t: math.log((N - freq + 0.5) / (freq + 0.5) + 1)
        for t, freq in df.items()
    }
    return {"idf": idf, "avg_dl": avg_dl, "k1": k1, "b": b}


def _bm25_score(query_tokens: list[str], doc_tokens: list[str], index: dict) -> float:
    k1, b, avg_dl, idf = index["k1"], index["b"], index["avg_dl"], index["idf"]
    dl = len(doc_tokens)
    tf_counter = Counter(doc_tokens)
    score = 0.0
    for t in query_tokens:
        if t not in idf:
            continue
        tf = tf_counter.get(t, 0)
        score += idf[t] * (tf * (k1 + 1)) / (
            tf + k1 * (1 - b + b * dl / max(avg_dl, 1))
        )
    return score


def _rank_skills(
    query: str, corpus: dict[str, list[str]], index: dict
) -> list[tuple[str, float]]:
    query_tokens = _tokenize(query)
    scores = {
        name: _bm25_score(query_tokens, tokens, index)
        for name, tokens in corpus.items()
    }
    return sorted(scores.items(), key=lambda kv: -kv[1])


# ── Corpus / fixture loaders ───────────────────────────────────────────────

def _load_corpus(skills_dir: Path) -> dict[str, list[str]]:
    """Return {skill_name: [tokens]} from each SKILL.md description field."""
    from validate import parse_frontmatter  # already on sys.path via conftest

    corpus: dict[str, list[str]] = {}
    for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
        fm = parse_frontmatter(skill_md)
        if fm and "description" in fm:
            corpus[skill_md.parent.name] = _tokenize(fm["description"])
    return corpus


def _load_sibling_sets(path: Path) -> list[set[str]]:
    """Parse skill_sibling_sets.txt into a list of skill-name sets."""
    if not path.is_file():
        return []
    result = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        result.append({s.strip() for s in line.split(",") if s.strip()})
    return result


def _collect_fixtures(skills_dir: Path) -> list[tuple[str, str]]:
    """Return [(skill_name, prompt)] from skills/*/triggers.txt."""
    fixtures: list[tuple[str, str]] = []
    for triggers_txt in sorted(skills_dir.glob("*/triggers.txt")):
        skill_name = triggers_txt.parent.name
        for line in triggers_txt.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                fixtures.append((skill_name, stripped))
    return fixtures


# ── Module-scope fixtures (load real skills once per session) ─────────────
# These fixtures read from _SKILLS_DIR (an absolute Path constant in this module).
# They are unaffected by the autouse reset_validate fixture in conftest.py,
# which only patches validate.ROOT and is irrelevant to this test module.

@pytest.fixture(scope="module")
def real_corpus():
    return _load_corpus(_SKILLS_DIR)


@pytest.fixture(scope="module")
def real_index(real_corpus):
    return _build_bm25_index(real_corpus)


@pytest.fixture(scope="module")
def sibling_sets():
    return _load_sibling_sets(_SIBLING_SETS_FILE)


# ── Parametrized harness ───────────────────────────────────────────────────

_FIXTURES = _collect_fixtures(_SKILLS_DIR)
assert _FIXTURES, (
    f"No trigger fixtures found under {_SKILLS_DIR} — "
    "check that skills/*/triggers.txt files exist"
)


@pytest.mark.parametrize(
    "skill_name,prompt",
    _FIXTURES,
    ids=[f"{s}::{p[:50]}" for s, p in _FIXTURES],
)
def test_prompt_ranks_target_skill_top1(
    skill_name, prompt, real_corpus, real_index, sibling_sets
):
    ranked = _rank_skills(prompt, real_corpus, real_index)
    target_rank = next(
        (i for i, (n, _) in enumerate(ranked) if n == skill_name), None
    )
    assert target_rank is not None, f"skill `{skill_name}` not found in corpus"

    if target_rank == 0:
        return  # top-1 globally; pass

    # Sibling-set escape hatch: all outrankers must be documented siblings.
    my_siblings = next(
        (s for s in sibling_sets if skill_name in s), {skill_name}
    )
    outrankers = [n for n, _ in ranked[:target_rank]]
    if all(n in my_siblings for n in outrankers):
        return

    non_sibling = [(n, sc) for n, sc in ranked[:target_rank] if n not in my_siblings]
    pytest.fail(
        f"prompt for `{skill_name}` ranked #{target_rank + 1}; "
        f"outranked by: "
        + ", ".join(f"`{n}` (score {sc:.2f})" for n, sc in non_sibling)
        + f". Refine skills/{skill_name}/SKILL.md description "
        f"or add a sibling-set entry to tests/skill_sibling_sets.txt."
    )


# ── Deliberate-vague acceptance test (acceptance criterion #5) ───────────

def test_deliberately_vague_description_is_flagged():
    """A synthetic corpus with a vague description must lose to a specific one.

    Uses a fully self-contained synthetic corpus — no real skills/ files are read.
    The skill name 'synthetic-specific-skill' is intentionally not a real skill.
    """
    synthetic_corpus = {
        "synthetic-vague-skill": _tokenize("A skill that does general programming things"),
        "synthetic-specific-skill": _tokenize(
            "Test-Driven Development TDD red-green-refactor test-first spec-first "
            "Arrange-Act-Assert FIRST principles writing tests before code fast isolated"
        ),
    }
    index = _build_bm25_index(synthetic_corpus)
    prompt = (
        "how do I start implementing this feature using test-driven development "
        "red green refactor writing the test first"
    )
    ranked = _rank_skills(prompt, synthetic_corpus, index)
    assert ranked[0][0] == "synthetic-specific-skill", (
        f"synthetic-vague-skill unexpectedly ranked #1 (score {ranked[0][1]:.2f}) — "
        "BM25 IDF weighting may be broken."
    )
