# MVC — Rust — Product Catalog

## Problem
Display a filtered list of products. Rust has no inheritance — MVC maps to structs and
`impl` blocks. Members ordered `pub > pub(crate) > private (no modifier)`. Note: struct
fields are private even when the struct is `pub`, requiring explicit `pub` per field.

## Implementation

```rust
// file: model.rs
#[derive(Debug, Clone)]
pub struct Product {
    pub id: u32,
    pub name: String,
    pub category: String,
    pub price: f64,
}

pub struct ProductModel {
    products: Vec<Product>, // private: only ProductModel mutates this
}

impl ProductModel {
    pub fn new(products: Vec<Product>) -> Self {
        Self { products }
    }

    pub fn by_category(&self, category: &str) -> Vec<&Product> {
        self.products.iter().filter(|p| p.category == category).collect()
    }
}
```

```rust
// file: view.rs
use crate::model::Product;

pub struct ProductView;

impl ProductView {
    pub fn render(&self, products: &[&Product]) {
        for p in products {
            println!("[{}] {} — ${:.2}", p.id, p.name, p.price);
        }
    }

    pub fn render_empty(&self, category: &str) {
        println!("No products in category {:?}.", category);
    }
}
```

```rust
// file: controller.rs
use crate::{model::ProductModel, view::ProductView};

pub struct ProductController {
    model: ProductModel,
    view: ProductView,
}

impl ProductController {
    pub fn new(model: ProductModel, view: ProductView) -> Self {
        Self { model, view }
    }

    pub fn show_by_category(&self, category: &str) {
        let products = self.model.by_category(category);
        if products.is_empty() {
            self.view.render_empty(category);
        } else {
            self.view.render(&products);
        }
    }
}
```

## Common Mistake
Making the `products` field `pub`, letting callers filter it directly and bypassing the Model's API.

```rust
// ✗ Public field breaks encapsulation — filtering logic scatters across callers
pub struct BadProductModel {
    pub products: Vec<Product>, // ✗ callers can now filter/mutate without going through the model
}

// call site:
let filtered: Vec<&Product> = model.products.iter()
    .filter(|p| p.category == "books") // ✗ filtering rule now lives everywhere
    .collect();
```
