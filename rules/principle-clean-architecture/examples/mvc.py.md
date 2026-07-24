# MVC — Python — Product Catalog

## Problem
Display a filtered list of products. Python MVC relies on naming conventions for
visibility: public (no underscore) → `_protected` (internal to class) → `__private`
(name-mangled). There are no access modifiers — the convention IS the contract.

## Implementation

```python
# file: model.py
from dataclasses import dataclass


@dataclass(frozen=True)
class Product:
    id: int
    name: str
    category: str
    price: float


class ProductModel:
    def __init__(self, products: list[Product]) -> None:
        self._products = list(products)  # _protected: model owns this, callers don't touch it

    def by_category(self, category: str) -> list[Product]:
        return [p for p in self._products if p.category == category]
```

```python
# file: view.py
from model import Product


class ProductView:
    def render(self, products: list[Product]) -> None:
        for p in products:
            print(f"[{p.id}] {p.name} — ${p.price:.2f}")

    def render_empty(self, category: str) -> None:
        print(f"No products in category {category!r}.")
```

```python
# file: controller.py
from model import ProductModel
from view import ProductView


class ProductController:
    def __init__(self, model: ProductModel, view: ProductView) -> None:
        self._model = model
        self._view = view

    def show_by_category(self, category: str) -> None:
        products = self._model.by_category(category)
        if products:
            self._view.render(products)
        else:
            self._view.render_empty(category)
```

## Common Mistake
Printing from the Model instead of returning data for the View to format.

```python
# ✗ Model doing presentation — output belongs in the View layer
class BadProductModel:
    def show_by_category(self, category: str) -> None:  # ✗ "show" implies UI responsibility
        for p in self._products:
            if p.category == category:
                print(f"[{p.id}] {p.name}")  # ✗ formatting belongs in ProductView
```
