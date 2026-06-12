# Light DDD — Java — Order Aggregate

## Problem

Java records give value-object semantics with zero boilerplate: `equals`, `hashCode`,
and accessors are generated, so `Money` is compared by value without a custom `equals`.
The `Order` aggregate root keeps its `lines` list private; the only mutation paths are
`addLine` and `submit`, which enforce the invariant that lines cannot be added once
an order is submitted.

## Implementation

```java
// file: Money.java
public record Money(long minorUnits, String currency) {
    public Money plus(Money other) {
        if (!this.currency.equals(other.currency)) {
            throw new IllegalArgumentException(
                "currency mismatch: " + this.currency + " vs " + other.currency);
        }
        return new Money(this.minorUnits + other.minorUnits, this.currency);
    }
}
```

```java
// file: Order.java
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

public class Order {

    public record OrderLine(String sku, Money price) {}

    private enum Status { DRAFT, SUBMITTED }

    private final String id;
    private Status status = Status.DRAFT;
    private final List<OrderLine> lines = new ArrayList<>();

    public Order(String id) { this.id = id; }

    public void addLine(String sku, Money price) {
        if (status == Status.SUBMITTED) {
            throw new IllegalStateException("cannot add lines to a submitted order");
        }
        lines.add(new OrderLine(sku, price));
    }

    public void submit() { this.status = Status.SUBMITTED; }

    public int lineCount() { return lines.size(); }

    public List<OrderLine> getLines() {
        return Collections.unmodifiableList(lines); // defensive copy — callers cannot mutate
    }

    public String getId() { return id; }
}
```

```java
// file: OrderRepository.java
import java.util.Optional;

public interface OrderRepository {
    Optional<Order> find(String id);
    void save(Order order);
}
```

```java
// file: Main.java
public class Main {
    public static void main(String[] args) {
        Order order = new Order("ord-1");
        order.addLine("SKU-1", new Money(1299, "USD"));
        order.submit();
        try {
            order.addLine("SKU-2", new Money(500, "USD"));
        } catch (IllegalStateException e) {
            System.out.println("rejected: " + e.getMessage());
            // rejected: cannot add lines to a submitted order
        }
    }
}
```

## Common Mistake

Returning the internal `List<OrderLine>` directly lets callers call `.add()` on it,
bypassing the aggregate root and silently breaking the submitted-order invariant.

```java
public List<OrderLine> getLines() {
    return lines; // ✗ callers can call lines.add(...) after submit() — invariant broken
}
```
