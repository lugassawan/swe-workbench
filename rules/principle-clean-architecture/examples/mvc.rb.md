# MVC — Ruby — Product Catalog

## Problem
Display a filtered list of products. Ruby enforces visibility through conventions:
`private` restricts methods; instance variables are inaccessible without an explicit
reader. No Rails — PORO style, where the convention IS the contract.

## Implementation

```ruby
# frozen_string_literal: true
# file: model.rb

Product = Data.define(:id, :name, :category, :price)

class ProductModel
  def initialize(products)
    @products = products.dup.freeze
  end

  def by_category(category)
    @products.select { |p| p.category == category }
  end
end
```

```ruby
# frozen_string_literal: true
# file: view.rb

class ProductView
  def render(products)
    products.each { |p| puts "[#{p.id}] #{p.name} — $#{format('%.2f', p.price)}" }
  end

  def render_empty(category)
    puts "No products in category \"#{category}\"."
  end
end
```

```ruby
# frozen_string_literal: true
# file: controller.rb

class ProductController
  def initialize(model, view)
    @model = model
    @view  = view
  end

  def show_by_category(category)
    products = @model.by_category(category)
    if products.empty?
      @view.render_empty(category)
    else
      @view.render(products)
    end
  end
end
```

## Common Mistake
Using `attr_accessor :products` instead of omitting the accessor — the generated writer
lets callers replace or mutate the model's collection.

```ruby
# ✗ attr_accessor generates a writer — callers can swap the entire collection
class BadProductModel
  attr_accessor :products  # ✗ .products= is now public

  def initialize(products)
    @products = products
  end
end

# Callers can now do:
# model.products = []           # ✗ wipes model state
# model.products.push(ghost)    # ✗ mutates the live array
```
