# DIP & OCP — Java — Payment Processing

## Problem
`OrderService` declares a `PaymentGateway` interface and depends only on that abstraction.
Java's explicit `implements` keyword makes the inversion visible in the type hierarchy.
Adding `PayPalGateway` is a new class in a new file; `OrderService` is never modified (OCP).
The gateway is constructor-injected so the service never calls `new StripeGateway()` (DIP).

## Implementation

```java
// file: PaymentGateway.java
public interface PaymentGateway {
    boolean charge(int amountCents, String reference);
}
```

```java
// file: StripeGateway.java
public class StripeGateway implements PaymentGateway {
    @Override
    public boolean charge(int amountCents, String reference) {
        System.out.printf("Stripe: charging %d¢ for %s%n", amountCents, reference);
        return true;
    }
}
```

```java
// file: PayPalGateway.java
// Adding PayPal requires no edits to OrderService — this is OCP.
public class PayPalGateway implements PaymentGateway {
    @Override
    public boolean charge(int amountCents, String reference) {
        System.out.printf("PayPal: charging %d¢ for %s%n", amountCents, reference);
        return true;
    }
}
```

```java
// file: OrderService.java
public class OrderService {
    private final PaymentGateway gateway; // injected — never newed-up here (DIP)

    public OrderService(PaymentGateway gateway) {
        this.gateway = gateway;
    }

    public boolean placeOrder(String item, int amountCents) {
        System.out.println("Placing order for \"" + item + "\"");
        return gateway.charge(amountCents, item);
    }
}
```

## Common Mistake

```java
// ✗ DIP violation — OrderService constructs the concrete class
// ✗ OCP violation — adding PayPal requires editing placeOrder
public class BadOrderService {
    public boolean placeOrder(String item, int cents, String method) {
        if ("stripe".equals(method)) {                      // ✗ switch on payment type
            return new StripeGateway().charge(cents, item); // ✗ newing concrete dep
        } else if ("paypal".equals(method)) {               // ✗ edit required per new provider
            return new PayPalGateway().charge(cents, item);
        }
        return false;
    }
}
```
