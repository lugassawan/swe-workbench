# MVC — Kotlin — Product Catalog

## Problem
Display a filtered list of products. Kotlin's data classes own the Model (no boilerplate
getters/setters). Members ordered `public > internal > private`; Kotlin defaults to
`public`, so focus on marking what is *restricted*.

## Implementation

```kotlin
// file: Product.kt
data class Product(
    val id: Int,
    val name: String,
    val category: String,
    val price: Double,
)
```

```kotlin
// file: ProductModel.kt
class ProductModel(private val products: List<Product>) {

    fun byCategory(category: String): List<Product> =
        products.filter { it.category == category }
}
```

```kotlin
// file: ProductView.kt
class ProductView {

    fun render(products: List<Product>) {
        products.forEach { p ->
            println("[${p.id}] ${p.name} — ${"%.2f".format(p.price)}")
        }
    }

    fun renderEmpty(category: String) {
        println("No products in category \"$category\".")
    }
}
```

```kotlin
// file: ProductController.kt
class ProductController(
    private val model: ProductModel,
    private val view: ProductView,
) {
    fun showByCategory(category: String) {
        val products = model.byCategory(category)
        if (products.isEmpty()) view.renderEmpty(category)
        else view.render(products)
    }
}
```

## Common Mistake
Performing filtering in the Controller rather than delegating to the Model.

```kotlin
// ✗ Controller doing model work — filtering rule belongs in ProductModel
fun showByCategory(category: String) {
    val filtered = model.allProducts()        // ✗ model exposes raw list
        .filter { it.category == category }   // ✗ filtering logic leaks into controller
    if (filtered.isEmpty()) view.renderEmpty(category)
    else view.render(filtered)
}
```
