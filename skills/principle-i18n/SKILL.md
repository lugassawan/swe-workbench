---
name: principle-i18n
description: Internationalization (i18n) & localization (l10n) principles — locale-aware date, time, number, and currency formatting, time-zone correctness (persist UTC in DB, render local), CLDR plural rules, message catalogs (ICU MessageFormat, gettext), translatable string composition (no concatenation), bidirectional & right-to-left layout, character-encoding hygiene, sortable date formats (ISO 8601). Auto-load when adding a new locale, formatting dates/times/numbers/currency for display, persisting timestamps, building message catalogs, composing user-facing strings from variables, designing pluralized copy, working with right-to-left scripts, choosing between backend and frontend locale negotiation, or auditing existing UI strings for translation readiness.
---

# Internationalization & Localization Principles

i18n bugs are latent — they survive review unnoticed and only surface when the product expands to a new locale.

## Locale-Aware Formatting

*Use platform APIs that accept a locale tag; never hand-roll date or number rendering.*

- Use `Intl.DateTimeFormat(locale, options)` and `Intl.NumberFormat(locale, options)` — not `Date.toString()`, `toLocaleDateString()` without a locale argument, or manual template strings.
- Pass BCP 47 locale tags (`en-US`, `fr-FR`, `ar-EG`); rely on CLDR data in the runtime rather than custom format maps.
- Never hard-code `MM/DD/YYYY` — format order, separator, and calendar system (Gregorian vs. Hijri vs. Buddhist Era) vary by locale.
- Currency: let `Intl.NumberFormat(locale, { style: 'currency', currency: 'USD' })` place the symbol and decide sign position — never concatenate `"$" + amount`.
- For backend rendering, thread the `Accept-Language` header or a persisted locale preference down to the formatting layer.

## Time Zones: Persist UTC, Render Local

*Timestamps recorded in local time become ambiguous at DST boundaries and when users cross time zones.*

- Persist all timestamps as `TIMESTAMP WITH TIME ZONE` in UTC in the database; never persist local time without an offset.
- Convert to the user's local zone at the display edge (UI component or API response serialiser), not in business logic or queries.
- Account for DST gaps and folds: `America/New_York` can produce two instants for the same clock time during the fall-back hour.
- Prefer named IANA zones (`Asia/Kolkata`) over fixed offsets (`+05:30`) — offsets do not encode DST history.
- When comparing or sorting, always compare UTC epoch values; wall-clock comparisons are incorrect across DST changes.

## Plural & Grammatical Rules

*English has two plural forms; Arabic has six; Russian has four (one/few/many/other) — selection depends on the last digit, with a special-case exclusion for 11–14.*

- Use CLDR plural categories (`zero`, `one`, `two`, `few`, `many`, `other`) via your i18n framework — never branch on `count === 1`.
- Every message with a numeric value needs all applicable CLDR forms supplied in the message catalog, even if the current locale only uses two.
- Where the framework supports it, handle grammatical gender and case agreement for languages that require them (German, Slavic, Romance).
- String templates like `"You have " + count + " messages"` break for Arabic, Polish, and Russian — use ICU `{count, plural, one{# message} other{# messages}}`.

## Message Catalogs & String Composition

*Translatable strings must be atomic, reorderable units — not assembled at runtime.*

- Use ICU MessageFormat or gettext-style catalogs: `t("greeting.user", { name })` not `"Hello " + name + "!"`.
- Never concatenate translatable fragments: `t("prefix") + value + t("suffix")` produces ungrammatical output for SOV/VSO word-order languages.
- Placeholders must be positional or named so translators can reorder them: `{0} added {1} to the cart` → translator may need `{1} wurde von {0} in den Warenkorb gelegt`.
- Keep translatable strings in source control alongside code; treat missing translation keys as build errors, not silent fallbacks.
- Separate presentation (HTML/Markdown within the translated string) from translation only when the framework handles it safely — raw HTML interpolation is an XSS vector.

## Bidirectional & Locale-Sensitive Layout

*Arabic, Hebrew, Persian, and Urdu are right-to-left; layouts that assume LTR break visually and semantically for these locales.*

- Set `dir="rtl"` on the `<html>` element (or the nearest container) when serving RTL locales; do not rely on CSS alone.
- Use logical CSS properties (`margin-inline-start`, `padding-inline-end`, `text-align: start`) instead of physical ones (`margin-left`, `text-align: left`) in shared layout styles.
- Mirror directional icons (back/forward arrows, progress indicators) in RTL — decorative icons and logos typically do not need mirroring.
- Wrap user-supplied content (names, addresses, product titles) in `<bdi>` or apply `unicode-bidi: isolate` to prevent bidi algorithm spillover into surrounding UI text.
- Test layout with a real RTL locale string, not just `dir="rtl"` on placeholder text.

## Encoding, Collation & Sortable Formats

*Encoding mismatches and locale-insensitive sort orders corrupt data and produce wrong results.*

- Use UTF-8 end-to-end: database columns, file storage, HTTP responses (`Content-Type: text/html; charset=utf-8`), and source files. Never introduce `latin1` or `iso-8859-1`.
- Sort user-visible strings with `Intl.Collator(locale, { sensitivity: 'base' })` — `Array.prototype.sort()` uses Unicode code-point order, which is wrong for most locales.
- Use ISO 8601 (`YYYY-MM-DDTHH:mm:ssZ`) for machine-readable timestamps in logs, filenames, and APIs — it sorts correctly as a plain string and is unambiguous across locales.
- Never sort `MM/DD/YYYY` date strings lexicographically — alphabetical order is not chronological order for that format.

## When i18n Engineering is Overkill

- Internal CLI tools or admin dashboards with a documented single-locale user population.
- Throwaway prototypes that will never reach end users.
- English-locked tooling where internationalisation is explicitly out of scope and that decision is documented.
- Any public-facing or multi-locale UI: never overkill regardless of timeline or team size.

## Red Flags

| Flag | Problem |
|------|---------|
| `new Date().toString()` or `toLocaleString()` without a locale argument | Output is runtime-locale-dependent; differs across servers and user machines |
| `if (count === 1) "1 item" else count + " items"` | Breaks for Arabic (6 forms), Russian (4 forms: one/few/many/other), Polish (3 integer forms) |
| `"Welcome " + name + "!"` as a translatable unit | Concatenation prevents word-order reordering for SOV/VSO languages |
| Persisting timestamps in a DB column without time-zone info | Ambiguous at DST boundaries; breaks when users move time zones |
| `padding-left` / `text-align: left` in shared layout styles | Breaks RTL locales; use logical properties instead |
| Hardcoded currency symbol position (`"$" + amount`) | Symbol placement and spacing vary by locale |
| Sorting date strings in `MM/DD/YYYY` format lexicographically | Alphabetical ≠ chronological for that format |
| `latin1` or `iso-8859-1` anywhere in the stack | Corrupts multibyte characters; breaks emoji and CJK text |
| Hand-rolled plural map keyed by language name | Misses CLDR-defined forms; fails for newly added locales |
| Translatable string assembled from separately-translated fragments | Produces ungrammatical output for languages with different word order |
