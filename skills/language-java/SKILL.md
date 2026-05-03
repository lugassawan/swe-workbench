---
name: language-java
description: Java best practices. Auto-load when working with .java, pom.xml, build.gradle, or when user mentions JVM, Spring, or concurrency.
---

## Java Best Practices
## Modern Java
Prefer records for immutable data carriers

Use sealed classes for controlled inheritance

Use var for readability (not overuse)

## Collections
Prefer List.of(), Map.of() for immutability

Avoid nulls — use Optional

Concurrency
Use virtual threads (Project Loom) where possible

Prefer ExecutorService over manual threads

Avoid shared mutable state

## Error Handling
Use checked exceptions for recoverable cases

Use runtime exceptions for programming errors

Never swallow exceptions

## Streams & Functional Style
Prefer streams for transformations

Avoid complex nested streams (readability matters)

## Spring Ecosystem
Use constructor injection

Avoid field injection

Keep controllers thin, move logic to services

## Build Tools
Maven (pom.xml) or Gradle (build.gradle)

Keep dependencies minimal

## Testing
Use JUnit + Mockito

Test behavior, not implementation

