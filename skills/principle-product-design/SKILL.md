---
name: principle-product-design
description: UX and product design principles — Nielsen's 10 usability heuristics, visual hierarchy, information architecture, interaction design patterns, design-system compliance, and responsive layout. Accessibility/WCAG conformance is delegated to `swe-workbench:principle-accessibility`. Auto-load when reviewing UX, evaluating usability, checking interaction patterns, assessing visual hierarchy or information architecture, auditing design-system compliance, or planning user-facing features.
---

# Product Design Principles

## Usability Heuristics (Nielsen's 10)

Every user-facing component must satisfy these. Violations block progress.

| Heuristic | Rule | Common Violation |
|---|---|---|
| **Visibility of system status** | Users always know what's happening | No loading indicator during async operations; silent failures with no feedback |
| **Match between system and real world** | Use language and concepts users know | Developer jargon in UI labels ("null", "undefined", "404"); unfamiliar abbreviations |
| **User control and freedom** | Provide undo, cancel, and escape routes | Destructive action with no confirmation; no way to cancel an in-progress operation |
| **Consistency and standards** | Same action, same result, everywhere | Button styles that vary across views; inconsistent terminology for the same concept |
| **Error prevention** | Prevent errors before they happen | Allowing invalid input submission; no constraints on date ranges or numeric fields |
| **Recognition over recall** | Show options, don't force memorization | Hidden navigation requiring memorized paths; no search/filter on long lists |
| **Flexibility and efficiency** | Support both novice and expert users | No keyboard shortcuts for power users; no progressive disclosure for complex forms |
| **Aesthetic and minimalist design** | Every element earns its place | Cluttered layouts with competing visual weights; information overload on a single view |
| **Error recovery** | Clear error messages with actionable next steps | "Something went wrong" with no guidance; error messages using technical stack traces |
| **Help and documentation** | Contextual help where users need it | No tooltips on ambiguous icons; no onboarding for complex features |

## Visual Hierarchy

Users scan, they don't read. Guide their attention.

| Principle | Rule | Common Violation |
|---|---|---|
| **Size communicates importance** | Primary content largest, secondary smaller, tertiary smallest | All text same size; critical numbers not emphasized |
| **Weight directs attention** | Bold for key data, regular for supporting content | Everything bold (nothing stands out) or everything light (nothing anchors) |
| **Color creates meaning** | Semantic colors for states (profit/loss, success/error), muted for secondary | Arbitrary color usage; profit shown in red (wrong cultural mapping) |
| **Spacing creates grouping** | Related items closer together, unrelated items further apart | Uniform spacing everywhere; no visual relationship between elements |
| **Alignment creates order** | Consistent alignment grid; numbers right-aligned in tables | Mixed alignment; numbers left-aligned making comparison impossible |
| **Whitespace prevents overload** | Generous padding around content blocks; breathing room between sections | Cramped layouts; every pixel filled with content |

## Information Architecture

Apply when features involve navigation, content structure, or multi-step flows.

| Pattern | When to Use | Key Rule |
|---|---|---|
| **Clear navigation** | Any app with multiple views | User always knows where they are and how to get back |
| **Logical grouping** | Content with multiple categories | Group by user mental model, not implementation structure |
| **Content prioritization** | Views with mixed-importance content | Most important content visible first; progressive disclosure for details |
| **Search and filter** | Lists with >10 items | Provide search for text content, filters for categorical data |
| **Breadcrumbs** | Hierarchical navigation deeper than 2 levels | Show full path; each segment clickable |

## Interaction Design

Apply when building interactive components, forms, or stateful UI.

| Pattern | Rule | Common Violation |
|---|---|---|
| **Immediate feedback** | Every user action gets a visible response within 100ms | Button click with no visual change until async completes |
| **Loading states** | Show skeleton or spinner for operations >300ms | Blank screen during data fetch; layout shift when content loads |
| **Empty states** | Meaningful message + action when no data exists | Blank area with no explanation; "No results" with no guidance |
| **Error states** | Specific message + recovery action for every failure mode | Generic error; error shown far from the source; no retry option |
| **Confirmation for destructive actions** | Require explicit confirmation before delete/remove/reset | Single-click delete with no undo; confirmation dialog with unclear consequences |
| **Progressive disclosure** | Show simple view first, reveal complexity on demand | All options visible at once on complex forms; no way to access advanced settings |
| **Optimistic updates** | Update UI immediately, reconcile on server response | Wait for server round-trip before showing change |

## Design System Compliance

When a design system exists (check `CLAUDE.md` or `docs/design-system.md`), enforce consistency.

| Rule | Enforcement |
|---|---|
| **Use existing tokens** | Colors, spacing, typography from the design system — never raw hex/px values for themed properties |
| **Use existing components** | Check component library before building new ones |
| **Follow naming conventions** | Component names, CSS classes, token names match established patterns |
| **Maintain visual consistency** | New components match the visual language of existing ones |
| **Document deviations** | If a design system rule is broken, document why explicitly |

## Responsive and Adaptive Design

Apply when building layouts that must work across screen sizes.

| Pattern | Rule |
|---|---|
| **Mobile-first** | Start with smallest layout, enhance for larger screens |
| **Fluid layouts** | Use relative units (%, rem, fr) over fixed px for layout dimensions |
| **Breakpoint strategy** | Define breakpoints by content needs, not device names |
| **Touch-friendly** | 44px minimum touch targets; adequate spacing between tappable elements |
| **Content reflow** | Content reflows gracefully — no horizontal scroll, no truncated critical info |

**Accessibility/WCAG conformance** (keyboard navigation, color contrast, ARIA, semantic HTML, screen-reader patterns) → `swe-workbench:principle-accessibility`.

## Rationalization Tables

### Usability Violation Excuses

| Excuse | Reality |
|---|---|
| "Users will figure it out" | They won't. They'll leave, complain, or misuse the feature. Design for clarity. |
| "It's obvious from context" | What's obvious to the builder is rarely obvious to the user. Test with fresh eyes. |
| "We don't have time for empty/error states" | An app without error states is an app that breaks silently. Users lose trust faster than you think. |
| "Loading states are polish, not essential" | A blank screen with no feedback makes users click again, creating duplicate actions. Loading states prevent errors. |
| "The user will only do this once" | First impressions determine whether users return. One-time flows need the most guidance. |
| "Power users don't need hand-holding" | Even power users need system status visibility, error recovery, and consistent behavior. Heuristics apply universally. |

### Visual Design Violation Excuses

| Excuse | Reality |
|---|---|
| "It matches the mockup" | Mockups don't cover all states, screen sizes, or data variations. Validate against principles, not just pixels. |
| "Consistent spacing is nitpicking" | Inconsistent spacing creates subconscious unease. Users can't articulate why it feels "off" but they notice. |
| "The data determines the layout" | You determine how data is presented. No dataset should break your visual hierarchy. Design for extremes. |
| "We'll polish it in a design pass" | Polishing 50 components later costs more than getting 1 component right now. Visual quality is not a phase. |

## Red Flags — STOP and Reassess

- Interactive element using `<div>` or `<span>` instead of semantic HTML (see `principle-accessibility` for the correct elements)
- Color as the only way to communicate state (red/green without icons or text)
- No loading indicator for any async operation
- Form with no validation feedback until submission
- Custom component that duplicates an existing design system component
- Layout that assumes specific data length (truncation without tooltip, overflow without scroll)
- Interactive element smaller than 44×44 px
- No visual feedback on hover, focus, or active states
- Error message that says "Error" or "Something went wrong" with no specifics

### If You Catch Yourself Thinking…

| Thought | What to Do Instead |
|---|---|
| "I'll add the loading state later" | Add it now. Define the three states (loading, content, error) before writing the content state. |
| "The contrast looks fine to me" | Check it. Use the project's semantic color tokens which should already meet WCAG AA. |
| "This doesn't need an empty state" | Every list, table, and data view needs an empty state. What does the user see when there's nothing to show? |
| "I'll match the existing pattern" | Check if the existing pattern meets usability heuristics first. Don't propagate violations. |
| "Users won't notice the inconsistent spacing" | They will — subconsciously. Use the design system's spacing tokens. |
| "This form is simple, no need for validation UX" | Every form needs inline validation, clear error messages, and prevented submission of invalid data. |
| "It works on my screen size" | Does it work at 320px? At 1440px? With 200% font scaling? Test the extremes. |

## UX Complexity Threshold

| Complexity | Interaction Pattern | States Required | Example |
|---|---|---|---|
| **Display only** | Static content, no interaction | Content, empty | Dashboard metric card, static label |
| **Simple interaction** | Single action, immediate result | Content, empty, loading, error, hover, focus | Toggle switch, single button action |
| **Form interaction** | User input with validation | Content, empty, loading, error, validation, disabled, success | Search input, settings form |
| **Complex flow** | Multi-step, stateful, conditional | All above + progress, confirmation, undo, partial error | Multi-step wizard, bulk operations, drag-and-drop |
