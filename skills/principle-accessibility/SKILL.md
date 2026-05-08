---
name: principle-accessibility
description: Accessibility (a11y) principles — WCAG 2.2 AA conformance, semantic HTML, ARIA roles/properties/states, keyboard navigation, focus management, focus traps, color contrast, alt text, screen reader compatibility, accessible names, landmark regions, reduced motion. Auto-load when reviewing frontend or UI code, evaluating ARIA usage, designing keyboard interaction, auditing color contrast, writing alt text, building modals or dialogs, handling focus, choosing between semantic elements and ARIA workarounds, or assessing screen-reader experience.
---

# Accessibility Principles

Accessibility bugs are correctness bugs. They are cheapest to fix before the first line of markup is written.

## Semantic HTML First

Native elements carry built-in roles, keyboard behavior, and accessible names — no ARIA required.

- Prefer `<button>` over `<div role="button">`; prefer `<a href>` over `<span onClick>`. Native elements are accessible by default.
- Use landmark elements (`<main>`, `<nav>`, `<header>`, `<footer>`, `<aside>`) to define regions screen readers can navigate directly.
- Maintain a logical heading hierarchy (`h1` → `h2` → `h3`); never skip levels to achieve visual styling.
- Mark up lists with `<ul>`/`<ol>` + `<li>` — screen readers announce item count and position.
- Use `<table>` with `<th scope>` and `<caption>` for tabular data; never for layout.

## ARIA: Use Sparingly

The first rule of ARIA: do not use ARIA if a native HTML element already provides the semantics.

- Never add redundant roles (`<button role="button">`) — they add noise without benefit.
- Every ARIA widget role has required owned elements and states; a `listbox` without `option` children is broken.
- Live regions (`aria-live`, `aria-atomic`) announce dynamic changes — use `assertive` only for time-critical alerts; default to `polite`.
- `aria-label` / `aria-labelledby` / `aria-describedby` are the canonical tools for providing accessible names when native labeling is insufficient.
- `aria-hidden="true"` on a focusable element is a contradiction — the element is both hidden from the tree and reachable by keyboard.

## Keyboard Navigation & Focus

Every user who cannot use a pointer must be able to reach and operate every interactive element via keyboard alone.

- All interactive elements must be reachable by Tab and operable by Enter/Space; use arrow keys for composite widgets (menus, tabs, grids).
- Preserve DOM source order as the logical tab order; avoid `tabindex` values > 0 (they override natural order globally).
- Visible focus indicators are required (WCAG 2.2 SC 2.4.11 AA): the indicator must have ≥3:1 contrast against adjacent colors *and* sufficient area (at minimum, a solid 2px outline around the component perimeter). A thin 1px outline at 3:1 passes contrast but fails on area.
- Modals must trap focus while open — Tab cycles through focusable children; Escape closes and restores focus to the trigger element.
- Skip links (`<a href="#main-content">`) let keyboard users bypass repeated navigation; place as the first focusable element on the page.

## Color, Contrast & Motion

Visual information conveyed by color alone is inaccessible to color-blind users.

- WCAG 2.2 AA contrast ratios: 4.5:1 for normal text, 3:1 for large text (≥18pt or ≥14pt bold), 3:1 for UI components and graphical objects.
- Never use color as the only means to convey meaning — pair with text, icon, or pattern (e.g., error = red + icon + label).
- Respect `prefers-reduced-motion`: declare animations normally, then disable or reduce them inside `@media (prefers-reduced-motion: reduce)`. The opt-in pattern (`no-preference`) is fragile in environments that do not evaluate media queries.
- WCAG 2.2 SC 2.5.8: touch/pointer targets must be ≥24×24 CSS px, or the offset from every adjacent target must be sufficient that a 24 px circle centred on each target does not intersect another.

## Screen Reader & Assistive Tech

Automated tools (axe, Lighthouse) catch ~40% of issues; manual testing with a real screen reader catches the rest.

- Every `<img>` needs an `alt` attribute — empty (`alt=""`) for decorative images, descriptive text for informative ones.
- Every form input needs an associated `<label>` via `for`/`id` or `aria-labelledby` — `placeholder` is not a label substitute.
- Status messages (save confirmation, cart update) must be announced without stealing focus: use a live region or `role="status"`.
- Test with VoiceOver (macOS/iOS), NVDA or JAWS (Windows) — screen reader support for ARIA diverges. axe passing is necessary but not sufficient.

## When Accessibility Engineering is Overkill

- Purely internal CLI tools with no graphical interface.
- Throwaway prototypes that will never be seen by end users.
- Admin tools with a documented legal exemption covering the specific user population.
- Public web and native UI: never overkill regardless of timeline or scope pressure.

## Red Flags

| Flag | Problem |
|------|---------|
| `<div onClick>` or `<span onClick>` without `role` + `tabindex` | Not keyboard-reachable; not announced to screen readers |
| Missing `alt` attribute on `<img>` | Image content invisible to screen readers |
| `tabindex="-1"` on an element with no roving-tabindex parent and no programmatic `focus()` call | Silently unreachable: excluded from sequential tab order and nothing focuses it programmatically |
| Modal without a focus trap | Tab escapes the dialog; background content becomes operable |
| Color-only error signaling | Color-blind users miss the error state entirely |
| `placeholder` used as the visible label | Disappears on input; fails contrast at default browser styles |
| `autofocus` on page load without user consent | Disorienting for screen reader users who have not yet reached that element |
| `aria-hidden="true"` on a focused element | Element is simultaneously hidden from the accessibility tree and keyboard-reachable |
| Missing or low-contrast focus indicator | Keyboard users lose their position in the page |
