---
name: solid
description: SOLID principles — single responsibility, open-closed, Liskov substitution, interface segregation, dependency inversion. Auto-load when designing classes, refactoring, reviewing object-oriented code, or discussing coupling, cohesion, or abstractions.
---

# SOLID

Five heuristics for OO design. Guidelines, not laws.

## S — Single Responsibility
*A module should have one reason to change.* Usually that means one *actor* it serves.
- **Good:** `InvoiceCalculator` computes totals; `InvoiceRenderer` formats output.
- **Bad:** `Invoice` that calculates, renders, emails, and persists.
- **Misapplied:** splitting a 20-line class into five 4-line classes. SRP is about change vectors, not line count.

## O — Open-Closed
*Open for extension, closed for modification.* New behavior should not require editing stable code.
- **Good:** a payment processor iterates `PaymentMethod` implementations; new methods are new files.
- **Bad:** a giant `switch` on `paymentType` that every new method edits.
- **Misapplied:** introducing a plugin framework for three enum values that will never grow.

## L — Liskov Substitution
*Subtypes must be usable wherever the base type is expected, without surprising callers.*
- **Good:** `ReadOnlyList` is not a subtype of `MutableList` — don't force it.
- **Bad:** `Square extends Rectangle` overriding `setWidth` to also set height.
- **Misapplied:** forbidding inheritance entirely. LSP is about honoring contracts, not avoiding hierarchies.

## I — Interface Segregation
*Clients should not depend on methods they do not use.*
- **Good:** `Reader`, `Writer`, `Closer` composed as needed.
- **Bad:** one `IFileSystem` with 40 methods every consumer imports.
- **Misapplied:** one-method interfaces for every action, creating interface soup.

## D — Dependency Inversion
*Depend on abstractions, not concretions.* High-level policy does not import low-level detail.
- **Good:** `OrderService` depends on `PaymentGateway`; Stripe and PayPal adapters implement it.
- **Bad:** `OrderService` instantiates `StripeClient` directly.
- **Misapplied:** an interface for every class "just in case". Invert only for a real seam — testability, multiple implementations, architectural boundary.

**Every cross-boundary dependency MUST be an abstraction — no exceptions.** If Component A depends on Component B in a different architectural layer, A defines the interface in its own layer and B implements it. Same-layer dependencies may be direct.

## When SOLID hurts
- Tiny codebases where indirection costs more than it saves.
- Scripts and one-off jobs.
- Algorithms where the shape of the computation matters more than the shape of the objects.

SOLID is about making change cheap. If nothing is changing, it costs complexity for no return.

## Common Excuses — and Why They're Wrong

| Excuse | Reality |
|--------|---------|
| "Codebase is too small for interfaces" | Size doesn't change dependency direction. A 50-line module with `*SqliteStore` still can't be tested without a database. |
| "Adding fields to the existing struct is zero-friction" | Zero friction now, high coupling forever. SRP violation compounds with every new feature bolted onto the god struct. |
| "YAGNI — we don't need this abstraction yet" | If the dependency crosses a layer boundary, you need it NOW. Tests are a present requirement, not speculation. |
| "Splitting would require changing too many files" | The number of files changed is not a quality metric. Refactor cost grows over time — pay it early. |

## Red Flags — Stop and Reassess

- One struct with methods spanning persistence, business rules, AND external communication
- Concrete type for any dependency that crosses a layer boundary (e.g., `*SqliteStore` as a field type)
- Interface with 10+ methods when most callers use 2
- Subtype that panics or returns error for methods the base type declares it can handle
- Test file that requires a real database or network connection for domain logic

## If You Catch Yourself Thinking…

| Thought | What to Do Instead |
|---------|--------------------|
| "This struct just needs one more method" | Check SRP — does this add a second reason to change? |
| "Interfaces are overkill here" | Does the dependency cross a layer? Yes → interface. No negotiation. |
| "The entity is just data, logic goes elsewhere" | Anemic domain. Move behavior onto the entity. |
| "Let me import the store directly, it's faster" | Faster to write, impossible to test in isolation. Define the interface. |
| "YAGNI — we might never need another implementation" | DIP isn't about multiple implementations. It's about testability and decoupling. |
