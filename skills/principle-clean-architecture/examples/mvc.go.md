# MVC — Go — Product Catalog

## Problem
Display a filtered list of products. The Model owns data and filtering, the View formats
console output, the Controller wires them. Go has no classes — use structs, methods, and
exported (Capitalized) names for the public API.

## Implementation

```go
// file: model.go
package catalog

// Product is the domain type — exported, no ORM tags.
type Product struct {
	ID       int
	Name     string
	Category string
	Price    float64
}

// ProductModel owns filtering logic; products slice is unexported.
type ProductModel struct {
	products []Product
}

func NewProductModel(products []Product) *ProductModel {
	return &ProductModel{products: products}
}

func (m *ProductModel) ByCategory(cat string) []Product {
	var out []Product
	for _, p := range m.products {
		if p.Category == cat {
			out = append(out, p)
		}
	}
	return out
}
```

```go
// file: view.go
package catalog

import "fmt"

// ProductView formats output; it receives data, never fetches it.
type ProductView struct{}

func (v *ProductView) Render(products []Product) {
	for _, p := range products {
		fmt.Printf("[%d] %s — $%.2f\n", p.ID, p.Name, p.Price)
	}
}

func (v *ProductView) RenderEmpty(category string) {
	fmt.Printf("No products in category %q.\n", category)
}
```

```go
// file: controller.go
package catalog

// ProductController wires Model and View; it owns no business logic.
type ProductController struct {
	model *ProductModel
	view  *ProductView
}

func NewProductController(m *ProductModel, v *ProductView) *ProductController {
	return &ProductController{model: m, view: v}
}

func (c *ProductController) ShowByCategory(cat string) {
	products := c.model.ByCategory(cat)
	if len(products) == 0 {
		c.view.RenderEmpty(cat)
		return
	}
	c.view.Render(products)
}
```

## Common Mistake
Duplicating filtering logic in the Controller instead of delegating to the Model.

```go
// ✗ filtering rule living in the controller — it belongs in ProductModel
func (c *BadController) ShowByCategory(cat string) {
	var found []Product
	for _, p := range c.allProducts { // ✗ controller holds raw data
		if p.Category == cat {        // ✗ business rule duplicated here
			found = append(found, p)
		}
	}
	c.view.Render(found)
}
```
