# MVC — Java — Product Catalog

## Problem
Display a filtered list of products. Model owns data and filtering, View formats output,
Controller orchestrates. Java 17+: prefer records for immutable value types. Members
ordered `public > protected > private` within each class.

## Implementation

```java
// file: Product.java
public record Product(int id, String name, String category, double price) {}
```

```java
// file: ProductModel.java
import java.util.List;

public class ProductModel {
    private final List<Product> products;

    public ProductModel(List<Product> products) {
        this.products = List.copyOf(products);
    }

    public List<Product> byCategory(String category) {
        return products.stream()
            .filter(p -> p.category().equals(category))
            .toList();
    }
}
```

```java
// file: ProductView.java
import java.util.List;

public class ProductView {
    public void render(List<Product> products) {
        products.forEach(p ->
            System.out.printf("[%d] %s — $%.2f%n", p.id(), p.name(), p.price())
        );
    }

    public void renderEmpty(String category) {
        System.out.printf("No products in category \"%s\".%n", category);
    }
}
```

```java
// file: ProductController.java
import java.util.List;

public class ProductController {
    private final ProductModel model;
    private final ProductView view;

    public ProductController(ProductModel model, ProductView view) {
        this.model = model;
        this.view = view;
    }

    public void showByCategory(String category) {
        List<Product> products = model.byCategory(category);
        if (products.isEmpty()) {
            view.renderEmpty(category);
        } else {
            view.render(products);
        }
    }
}
```

## Common Mistake
Fetching data from inside the View. View should only format what it is given.

```java
// ✗ View coupling to data access — View should receive data, never fetch it
public class BadProductView {
    private final ProductRepository repo; // ✗ View owns a repository

    public void render(String category) {
        List<Product> products = repo.findByCategory(category); // ✗ fetching, not formatting
        products.forEach(p -> System.out.println(p.name()));
    }
}
```
