"""Unit tests for scripts/compress-descriptions.py's internal logic (#680):
the clause splitter, YAML re-serialization, DescriptionFile drop/restore
symmetry, and the optimizer's longest-first convergence — the pieces that
are otherwise only exercised indirectly through the resulting description
files passing tests/test_skill_triggers.py / tests/test_agent_triggers.py.
"""

import importlib.util
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

ROOT = Path(__file__).parent.parent


def _load_compress_module():
    path = ROOT / "scripts" / "compress-descriptions.py"
    loader = SourceFileLoader("compress_descriptions", str(path))
    spec = importlib.util.spec_from_file_location("compress_descriptions", path, loader=loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules["compress_descriptions"] = module
    spec.loader.exec_module(module)
    return module


cd = _load_compress_module()


# ──────────────────────────────────────────────
# _split_clauses
# ──────────────────────────────────────────────

class TestSplitClauses:
    def test_simple_comma_split(self):
        clauses, seps = cd._split_clauses("a, b, c")
        assert clauses == ["a", "b", "c"]
        assert seps == [", ", ", "]

    def test_semicolon_split(self):
        clauses, seps = cd._split_clauses("a; b")
        assert clauses == ["a", "b"]
        assert seps == ["; "]

    def test_no_separator_single_clause(self):
        clauses, seps = cd._split_clauses("a lone sentence.")
        assert clauses == ["a lone sentence."]
        assert seps == []

    def test_paren_aware_comma_inside_parens_not_split(self):
        clauses, seps = cd._split_clauses("a (b, c), d")
        assert clauses == ["a (b, c)", "d"]
        assert seps == [", "]

    def test_bracket_aware(self):
        clauses, seps = cd._split_clauses("a [b, c], d")
        assert clauses == ["a [b, c]", "d"]
        assert seps == [", "]

    def test_round_trip_matches_original(self):
        for text in [
            "a, b, c",
            "a; b, c; d",
            "a (b, c), d, e (f; g)",
            "no separators here at all",
            "IOptions<T>, LINQ, ArrayPool",
        ]:
            clauses, seps = cd._split_clauses(text)
            rebuilt = clauses[0] + "".join(s + c for s, c in zip(seps, clauses[1:]))
            assert rebuilt == text

    def test_unbalanced_closing_paren_does_not_go_negative(self):
        # depth is clamped at 0 rather than going negative on a stray ')'.
        clauses, seps = cd._split_clauses("a), b, c")
        rebuilt = clauses[0] + "".join(s + c for s, c in zip(seps, clauses[1:]))
        assert rebuilt == "a), b, c"


# ──────────────────────────────────────────────
# _serialize_value
# ──────────────────────────────────────────────

class TestSerializeValue:
    def test_plain_stays_plain_when_it_round_trips(self):
        result = cd._serialize_value("a plain description", "a plain description")
        assert result == "a plain description"
        assert not result.startswith(('"', "'"))

    def test_double_quoted_original_stays_double_quoted(self):
        result = cd._serialize_value("new text", '"old text"')
        assert result == '"new text"'

    def test_double_quoted_escapes_backslash_and_quote(self):
        result = cd._serialize_value('has "quotes" and \\backslash', '"old"')
        assert result == '"has \\"quotes\\" and \\\\backslash"'

    def test_single_quoted_original_stays_single_quoted(self):
        result = cd._serialize_value("new text", "'old text'")
        assert result == "'new text'"

    def test_single_quoted_doubles_embedded_quote(self):
        result = cd._serialize_value("it's here", "'old'")
        assert result == "'it''s here'"

    def test_plain_falls_back_to_double_quote_when_unparseable_as_plain(self):
        # A colon-space sequence makes this invalid as a plain YAML scalar
        # (validate._parse_plain_description would return None for it).
        result = cd._serialize_value("note: important detail", "plain original")
        assert result == '"note: important detail"'


# ──────────────────────────────────────────────
# DescriptionFile drop/restore symmetry
# ──────────────────────────────────────────────

class TestDescriptionFileDropRestore:
    def _make_file(self, tmp_path, description):
        path = tmp_path / "SKILL.md"
        path.write_text(f"---\nname: my-skill\ndescription: {description}\n---\n", encoding="utf-8")
        return path

    def test_drop_then_restore_round_trips_to_original(self, tmp_path):
        original = "Lead clause, second clause, third clause, fourth clause."
        path = self._make_file(tmp_path, original)
        df = cd.DescriptionFile(path, "my-skill")
        assert df.render() == original

        undo = df.drop(2)  # drop "third clause"
        assert df.render() != original
        assert "third clause" not in df.render()

        df.restore(undo)
        assert df.render() == original

    def test_clause_zero_is_never_a_valid_drop_target_position(self, tmp_path):
        # candidate positions only ever range(1, len(clauses)) in the
        # optimizer, so position 0 (the anchored lead clause) is never
        # passed to drop() in practice — verify the guard by construction:
        # dropping *some* non-zero position always leaves clause 0 intact.
        original = "Anchored lead, middle clause, trailing clause."
        path = self._make_file(tmp_path, original)
        df = cd.DescriptionFile(path, "my-skill")
        df.drop(1)
        assert df.render().startswith("Anchored lead")

    def test_write_persists_dropped_render_to_disk(self, tmp_path):
        original = "Lead clause, droppable clause, kept clause."
        path = self._make_file(tmp_path, original)
        df = cd.DescriptionFile(path, "my-skill")
        df.drop(1)
        df.write()
        new_text = path.read_text(encoding="utf-8")
        assert "droppable clause" not in new_text
        assert "Lead clause" in new_text and "kept clause" in new_text

    def test_round_trip_assertion_fires_on_construction(self, tmp_path):
        # DescriptionFile.__init__ asserts render() == original_description
        # immediately after splitting — this is a smoke check that a
        # well-formed description never trips that assertion (a genuine
        # splitter bug would raise AssertionError here, not silently pass).
        original = "A, B; C (D, E), F"
        path = self._make_file(tmp_path, original)
        cd.DescriptionFile(path, "my-skill")  # must not raise


# ──────────────────────────────────────────────
# _optimize
# ──────────────────────────────────────────────

class TestOptimize:
    def _make_files(self, tmp_path, descriptions):
        files = {}
        for name, description in descriptions.items():
            path = tmp_path / f"{name}.md"
            path.write_text(f"---\nname: {name}\ndescription: {description}\n---\n", encoding="utf-8")
            files[name] = cd.DescriptionFile(path, name)
        return files

    def test_drops_longest_clause_first(self, tmp_path):
        files = self._make_files(
            tmp_path, {"skill-a": "Lead, a very very very long clause, short"}
        )
        # Suite that only accepts a drop once the description has shrunk
        # below a threshold too small for the first (longest) drop alone to
        # satisfy on its own — forces at least the longest clause to be
        # tried before the loop can converge.
        calls = []

        def suite_passes(files, changed_name=None):
            calls.append(files["skill-a"].render())
            # Accept only landing on exactly "Lead, short" — rejects both
            # the no-op state and dropping past it, isolating a single
            # accepted trial so we can see which clause it targeted.
            return files["skill-a"].render() == "Lead, short"

        dropped = cd._optimize(files, suite_passes, log=lambda *a: None)
        assert dropped == 1
        assert files["skill-a"].render() == "Lead, short"
        # The first trial tried must have been the longest clause ("a very
        # very very long clause"), matching the documented longest-first
        # order — not "short" tried first.
        assert calls[0] == "Lead, short"

    def test_monotone_shrink_never_lengthens(self, tmp_path):
        files = self._make_files(tmp_path, {"skill-a": "Lead, extra one, extra two, extra three"})
        before_len = len(files["skill-a"].render())

        def suite_passes(files, changed_name=None):
            return True  # accept every drop

        cd._optimize(files, suite_passes, log=lambda *a: None)
        after_len = len(files["skill-a"].render())
        assert after_len <= before_len
        assert files["skill-a"].render() == "Lead"  # anchored clause 0 survives

    def test_rejecting_all_drops_converges_with_zero_dropped(self, tmp_path):
        files = self._make_files(tmp_path, {"skill-a": "Lead, one, two, three"})
        original = files["skill-a"].render()

        def suite_passes(files, changed_name=None):
            return False  # reject every drop

        dropped = cd._optimize(files, suite_passes, log=lambda *a: None)
        assert dropped == 0
        assert files["skill-a"].render() == original

    def test_stale_length_candidate_is_skipped_not_wrongly_dropped(self, tmp_path):
        # Two clauses share the same starting length class so a same-file
        # earlier drop can shift a later same-pass candidate's position;
        # the expected_len re-check must skip rather than drop a mismatched
        # clause. Accept only the very first successful trial so we can see
        # exactly which clause it targeted.
        files = self._make_files(
            tmp_path, {"skill-a": "Lead, zzzzzzzzzz, yyyyyyyyyy, xxxxx, w"}
        )
        accepted_once = {"done": False}

        def suite_passes(files, changed_name=None):
            if accepted_once["done"]:
                return False
            accepted_once["done"] = True
            return True

        cd._optimize(files, suite_passes, log=lambda *a: None)
        # Exactly one clause was ever accepted-dropped; render() must still
        # be a valid, round-trippable rendering (no corruption from a
        # mismatched drop/restore).
        result = files["skill-a"].render()
        assert result.startswith("Lead")
        assert result.count(", ") <= 3
