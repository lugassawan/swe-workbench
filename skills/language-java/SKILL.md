---
name: language-java
description: Java idioms — records, sealed types, virtual threads, streams, and JDK 21+ patterns. Auto-load when working with .java files, pom.xml, build.gradle, or when the user mentions Java, JVM, Spring, Maven, Gradle, records, sealed classes, or virtual threads.
---

# Java

## Records and sealed types
Modern Java models data without boilerplate.

```java
record Point(double x, double y) {}

sealed interface Shape permits Circle, Rectangle {}
record Circle(Point center, double radius) implements Shape {}
record Rectangle(Point topLeft, Point bottomRight) implements Shape {}
```

- Use `record` for immutable data carriers — equals, hashCode, toString, and accessors for free.
- `sealed` closes a hierarchy; exhaustive `switch` replaces `instanceof` chains.

```java
double area = switch (shape) {
    case Circle c    -> Math.PI * c.radius() * c.radius();
    case Rectangle r -> Math.abs(r.bottomRight().x() - r.topLeft().x())
                        * Math.abs(r.bottomRight().y() - r.topLeft().y());
};
```

## Optional and null discipline
- Return `Optional<T>` from methods that may have no result; never use it as a field or parameter type.
- `Optional` is not a null check replacement — it signals "absence is a valid outcome."
- Annotate parameters and fields with `@NonNull` / `@Nullable` for static analysis.

```java
Optional<User> find(String id) { ... }
find(id).map(User::email).orElseThrow(() -> new NotFoundException(id));
```

## Concurrency — virtual threads (JDK 21+)
Virtual threads (Project Loom) make blocking-style IO safe at scale.

```java
try (var scope = new StructuredTaskScope.ShutdownOnFailure()) {
    Future<User>  user  = scope.fork(() -> fetchUser(id));
    Future<Order> order = scope.fork(() -> fetchOrder(orderId));
    scope.join().throwIfFailed();
    return new Response(user.get(), order.get());
}
```

- `Executors.newVirtualThreadPerTaskExecutor()` — drop-in for `newCachedThreadPool()` with virtual-thread semantics.
- Do not pool virtual threads; create-per-task is the idiom.
- Watch for carrier-thread pinning: `synchronized` blocks and some native calls pin a virtual thread to its carrier. Prefer `ReentrantLock` when high-throughput blocking is expected.
- `StructuredTaskScope` (JDK 21–24 preview — not yet standard; enable with `--enable-preview`) enforces structured concurrency: tasks are joined before the scope exits.

## Error handling
- Prefer unchecked exceptions at boundaries; translate checked exceptions from libraries early.
- `try-with-resources` for anything `AutoCloseable` — never close in a `finally` block manually.
- Exception translation: catch a library-specific exception at the boundary, rethrow as your domain exception.

```java
try (var conn = dataSource.getConnection()) {
    // ...
} catch (SQLException e) {
    throw new RepositoryException("fetch user " + id, e);
}
```

## Streams and collections
- `Stream` for transformations; avoid imperative loops when a pipeline is clearer.
- `.toList()` (JDK 16+) over `Collectors.toList()` — returns an unmodifiable list.
- Use `List.of`, `Map.of`, `Set.of` for small immutable collections; `Map.copyOf` to defensively copy.

```java
List<String> emails = users.stream()
    .filter(User::isActive)
    .map(User::email)
    .toList();
```

## Build and packaging
- Maven: `pom.xml` with `<dependencyManagement>` for BOM imports; prefer the wrapper (`./mvnw`).
- Gradle: `build.gradle` (Groovy) or `build.gradle.kts` (Kotlin DSL — preferred for IDE support).
- JPMS (`module-info.java`): adopt only when publishing a library that needs strong encapsulation.

## Tooling
- **Imports/Format:** `mvn spotless:apply` / `./gradlew spotlessApply`
- **Lint:** `mvn checkstyle:check` / `./gradlew checkstyleMain`
- **Test:** `mvn test` / `./gradlew test` (see Testing below)

## Testing
- JUnit 5 (`@Test`, `@ParameterizedTest`, `@MethodSource`) — not JUnit 4.
- AssertJ for fluent assertions: `assertThat(actual).isEqualTo(expected)`.
- Mockito for external boundaries; do not mock domain objects.

```java
@ParameterizedTest
@MethodSource("provideInputs")
void computesTax(double income, double expectedTax) {
    assertThat(TaxCalculator.compute(income)).isCloseTo(expectedTax, within(0.01));
}
```

## Avoid
- Raw types (`List` instead of `List<String>`).
- Returning or passing `null` where `Optional` or a sentinel value communicates intent.
- Mutable `static` state outside of intentional singletons.
- `equals` without a matching `hashCode` override.
- Blocking inside a reactive pipeline or `CompletableFuture` chain.
