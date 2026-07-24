# Observer — Java — Order Status Notifications

## Problem

An `Order` moves through statuses — "shipped", "delivered" — and email, SMS, and audit systems
must all react independently. Hardcoding those calls in `Order` creates tight coupling: every
new channel requires modifying the domain class. The Observer pattern separates concerns by
having `Order` hold a list of `OrderObserver` implementations it notifies, while knowing nothing
about any concrete observer.

## Implementation

```java
// file: OrderObserver.java
public interface OrderObserver {
    void onStatusChanged(String status);
}
```

```java
// file: Order.java
import java.util.ArrayList;
import java.util.List;

public class Order {
    private final List<OrderObserver> observers = new ArrayList<>();
    private String status = "pending";

    public void addObserver(OrderObserver observer) {
        observers.add(observer);
    }

    private void notifyObservers() {
        for (OrderObserver o : observers) o.onStatusChanged(status);
    }

    public void ship() {
        status = "shipped";
        notifyObservers();
    }

    public void deliver() {
        status = "delivered";
        notifyObservers();
    }
}
```

```java
// file: Main.java
public class Main {
    public static void main(String[] args) {
        Order order = new Order();

        order.addObserver(s -> System.out.println("Email: order is now " + s));
        order.addObserver(s -> System.out.println("SMS: order is now " + s));
        order.addObserver(s -> System.out.println("Audit: status changed to " + s));

        order.ship();
        // Email: order is now shipped
        // SMS: order is now shipped
        // Audit: status changed to shipped
    }
}
```

## Common Mistake

Calling `EmailService` and `SmsService` directly inside `Order` makes `Order` responsible for
knowing every notification channel, and forces a code change whenever a new one is added.

```java
// ✗ Order directly calls services — adding a new notification requires editing Order
public void ship() {
    this.status = "shipped";
    emailService.send("shipped");   // ✗ hard dependency on EmailService
    smsService.send("shipped");     // ✗ hard dependency on SmsService
    // ✗ must edit Order to add audit log
}
```
