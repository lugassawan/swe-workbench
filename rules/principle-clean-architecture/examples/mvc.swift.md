# MVC — Swift — Product Catalog

## Problem
Display a filtered list of products. Swift structs are value types — the model's array
is a copy, not a shared reference. `private let` bindings and access control make layer
ownership explicit and enforce immutability without runtime overhead.

## Implementation

```swift
// file: Product.swift
struct Product {
    let id: Int
    let name: String
    let category: String
    let price: Double  // Double used for simplicity; production money values prefer Decimal
}
```

```swift
// file: ProductModel.swift
struct ProductModel {
    private let products: [Product]

    init(products: [Product]) {
        self.products = products
    }

    func byCategory(_ category: String) -> [Product] {
        products.filter { $0.category == category }
    }
}
```

```swift
// file: ProductView.swift
struct ProductView {
    func render(_ products: [Product]) {
        for p in products {
            print("[\(p.id)] \(p.name) — $\(String(format: "%.2f", p.price))")
        }
    }

    func renderEmpty(_ category: String) {
        print("No products in category \"\(category)\".")
    }
}
```

```swift
// file: ProductController.swift
struct ProductController {
    private let model: ProductModel
    private let view: ProductView

    init(model: ProductModel, view: ProductView) {
        self.model = model
        self.view  = view
    }

    func showByCategory(_ category: String) {
        let products = model.byCategory(category)
        if products.isEmpty {
            view.renderEmpty(category)
        } else {
            view.render(products)
        }
    }
}
```

## Common Mistake
Declaring `Product` as a `class` instead of a `struct` — class instances are reference
types, so the model's array stores a shared pointer; a caller holding the same instance
can mutate fields that the model thinks it owns.

```swift
// ✗ class Product shares references — callers can mutate the item after insertion
final class Product {       // ✗ reference type: array stores a pointer, not a copy
    var id: Int             // ✗ var fields enable post-insertion mutation
    var name: String
    var category: String
    var price: Double

    init(id: Int, name: String, category: String, price: Double) {
        self.id = id; self.name = name; self.category = category; self.price = price
    }
}

// let p = Product(id: 1, name: "Lens", category: "photo", price: 299)
// let model = ProductModel(products: [p])
// p.price = 0  // ✗ mutates the object already stored inside the model
```
