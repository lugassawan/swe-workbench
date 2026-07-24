# MVC — TypeScript — Product Catalog

## Problem
Display a filtered list of products. TypeScript defaults to `public`, but this example uses
explicit modifiers (`public`, `private`) on every member so that visibility intent is
readable at a glance without IDE hover. Members ordered `public > protected > private`.

## Implementation

```ts
// file: model.ts
export interface Product {
  id: number;
  name: string;
  category: string;
  price: number;
}

export class ProductModel {
  private products: Product[];

  public constructor(products: Product[]) {
    this.products = [...products];
  }

  public byCategory(category: string): Product[] {
    return this.products.filter((p) => p.category === category);
  }
}
```

```ts
// file: view.ts
import type { Product } from "./model";

export class ProductView {
  public render(products: Product[]): void {
    products.forEach((p) => {
      console.log(`[${p.id}] ${p.name} — $${p.price.toFixed(2)}`);
    });
  }

  public renderEmpty(category: string): void {
    console.log(`No products in category "${category}".`);
  }
}
```

```ts
// file: controller.ts
import { ProductModel } from "./model";
import { ProductView } from "./view";

export class ProductController {
  public constructor(
    private model: ProductModel,
    private view: ProductView,
  ) {}

  public showByCategory(category: string): void {
    const products = this.model.byCategory(category);
    if (products.length === 0) {
      this.view.renderEmpty(category);
    } else {
      this.view.render(products);
    }
  }
}
```

## Common Mistake
Typing model data as `any[]`, discarding the type contract that TypeScript provides.

```ts
// ✗ any[] loses the Product shape — downstream code can't trust field names
export class BadProductModel {
  private products: any[]; // ✗ callers have no idea what shape a product has

  public byCategory(category: string): any[] { // ✗ type information gone at call site
    return this.products.filter((p) => p.category === category);
  }
}
```
