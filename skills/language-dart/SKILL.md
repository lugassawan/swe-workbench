---
name: language-dart
description: Dart idioms — null safety, async/await, Futures and Streams, widget composition, and Riverpod/Bloc app architecture. Auto-load when working with .dart files, pubspec.yaml, or when the user mentions Dart, Flutter, widgets, Riverpod, Bloc, Streams, or null safety.
---

# Dart

## Null safety
- Sound null safety is on by default (Dart ≥2.12) — no unsound nulls sneak through.
- Non-nullable is the default; append `?` only when a value can genuinely be absent (`String? name`).
- `late` defers initialization for values assigned before first read (DI fields, `initState` fields) — a `late` field read before assignment throws.
- `!` (null-assertion) asserts non-null; prefer narrowing (`if (x != null)`) or `?.`/`??` over `!`, since `!` throws at runtime.
- `??=` for lazy default assignment; `??` for fallback expressions.

```dart
String greet(String? name) => 'Hello, ${name ?? 'stranger'}';
```

## Async — Futures and Streams
- `Future<T>` wraps a value that arrives later; `async`/`await` reads like sync code.
- Unhandled Future errors surface as unhandled exceptions — always `try`/`catch` around `await`, or attach `.catchError`.
- `Stream<T>` models a sequence over time; `await for` consumes it, `StreamController` produces it.
- `Completer<T>` bridges callback-based APIs into a `Future`.
- `Future.wait([...])` for concurrent futures; don't `await` sequentially in a loop when the work is independent.

```dart
Future<User> fetchUser(String id) async {
  try {
    final res = await api.get('/users/$id');
    return User.fromJson(res.data);
  } on DioException catch (e) {
    throw UserFetchException(id, e);
  }
}
```

## Widget composition
- `StatelessWidget` is the default; reach for `StatefulWidget` only when the widget owns mutable state across rebuilds.
- `build()` must be pure and fast — no side effects, no I/O; it can run many times per frame.
- Compose small widgets instead of deep inheritance — extract a widget class, not a private `_buildX()` method, when it needs its own `const` or rebuild boundary.
- `const` constructors on leaf widgets let Flutter skip rebuilding subtrees whose inputs didn't change.
- Pass a `Key` (`ValueKey`, `ObjectKey`) when reordering or diffing a list of like-typed widgets, or state attaches to the wrong element.

## State management — Riverpod and Bloc
- **Riverpod**: `Provider`/`NotifierProvider` declares state outside the widget tree; `ref.watch(p)` subscribes and rebuilds, `ref.read(p)` reads once (event handlers, not `build`).
- **Bloc**: a `Cubit` exposes methods that `emit` new states; a `Bloc` maps incoming `Event`s to `State`s via `on<Event>`. Widgets react via `BlocBuilder`/`BlocListener`.
- Both push state out of widgets and make it unit-testable without pumping a widget tree — pick per-team convention, don't mix them within the same feature.

```dart
final counterProvider = NotifierProvider<Counter, int>(Counter.new);

class Counter extends Notifier<int> {
  @override
  int build() => 0;
  void increment() => state++;
}
```

## Testing
- `flutter_test`: `testWidgets('description', (tester) async { ... })` drives a widget in an isolated binding.
- `tester.pumpWidget(...)` mounts; `tester.pump()` advances one frame, `tester.pumpAndSettle()` drains animations/microtasks.
- `find.text(...)`, `find.byType(...)`, `find.byKey(...)` locate widgets; assert with `expect(find.text('X'), findsOneWidget)`.
- `integration_test` runs the same API on a real device/emulator for end-to-end flows.
- Unit-test `Notifier`/`Cubit`/`Bloc` logic directly — no widget tree needed.

## Tooling
- **Format:** `dart format .`
- **Lint/analyze:** `dart analyze` (package) or `flutter analyze` (app) — configured via `analysis_options.yaml`.
- **Dependencies:** declared in `pubspec.yaml`; resolved with `dart pub get` / `flutter pub get`.
- **Test:** `flutter test` (widget/unit), `flutter test integration_test` (e2e).

## Idioms cheat sheet
- `final` over `var` when the reference won't be reassigned; `const` when the value is compile-time constant.
- Cascades (`obj..a()..b()`) for fluent multi-call setup.
- Named constructors (`User.fromJson(...)`) beat factory functions with boolean flags.
- Extension methods add behavior to existing types without subclassing.
- Records (`(int, String)`, `({int id, String name})`) for small ad-hoc multi-value returns, in place of a throwaway class.

## Avoid
- `!` as a habitual fix for the analyzer instead of proving non-null.
- Business logic inside `build()` — extract it into the state-management layer.
- Deeply nested `setState` widgets when a `Notifier`/`Cubit` would isolate the rebuild.
- Blocking synchronous work on the UI isolate — use `compute()` or a separate isolate for CPU-heavy work.
