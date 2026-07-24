# MVC — C# — Product Catalog

## Problem
Display a filtered list of products. C# records are concise immutable value types with
compiler-generated equality. Explicit access modifiers and LINQ make layer intent clear;
primary constructors (C# 12) eliminate boilerplate for simple injection.

## Implementation

```cs
// file: Product.cs
public sealed record Product(int Id, string Name, string Category, decimal Price);
```

```cs
// file: ProductModel.cs
using System.Collections.Generic;
using System.Linq;

public class ProductModel(IReadOnlyList<Product> products)
{
    public IReadOnlyList<Product> ByCategory(string category) =>
        products.Where(p => p.Category == category).ToList().AsReadOnly();
}
```

```cs
// file: ProductView.cs
using System.Collections.Generic;

public class ProductView
{
    public void Render(IReadOnlyList<Product> products)
    {
        foreach (var p in products)
            Console.WriteLine($"[{p.Id}] {p.Name} — ${p.Price:F2}");
    }

    public void RenderEmpty(string category) =>
        Console.WriteLine($"No products in category \"{category}\".");
}
```

```cs
// file: ProductController.cs
using System.Collections.Generic;

public class ProductController(ProductModel model, ProductView view)
{
    public void ShowByCategory(string category)
    {
        IReadOnlyList<Product> products = model.ByCategory(category);
        if (products.Count == 0)
            view.RenderEmpty(category);
        else
            view.Render(products);
    }
}
```

## Common Mistake
Exposing the internal collection as a mutable `List<Product>`, letting callers alter model state.

```cs
// ✗ Public List<T> leaks mutability — callers can add, remove, or clear items
public class BadProductModel
{
    public List<Product> Products { get; } = new();  // ✗ List<T> exposes mutation methods

    // Callers can do:
    // model.Products.Add(ghost);   // ✗ state mutated from outside the model
    // model.Products.Clear();      // ✗ collection emptied unintentionally
}
```
