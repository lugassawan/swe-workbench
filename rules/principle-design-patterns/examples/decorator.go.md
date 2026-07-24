# Decorator — Go — Retry and Logging Fetch

## Problem

A core HTTP fetch must gain retry and logging behavior without those concerns being
embedded in the fetch function itself. Go's first-class functions make the Decorator
pattern natural: `WithRetry` and `WithLogging` each accept a `FetchFn` and return a
new `FetchFn`, composable in any order. No interfaces or structs are required.

## Implementation

```go
// file: fetcher.go
package fetcher

import (
	"fmt"
	"io"
	"net/http"
)

// FetchFn is the core function type all decorators wrap.
type FetchFn func(url string) (string, error)

// HTTPFetch is the core implementation.
func HTTPFetch(url string) (string, error) {
	resp, err := http.Get(url) //nolint:gosec
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	b, err := io.ReadAll(resp.Body)
	return string(b), err
}

// WithRetry wraps fn, retrying up to n times on error.
func WithRetry(fn FetchFn, n int) FetchFn {
	return func(url string) (string, error) {
		var err error
		for i := 0; i <= n; i++ {
			var result string
			if result, err = fn(url); err == nil {
				return result, nil
			}
		}
		return "", err
	}
}

// WithLogging wraps fn, printing each request and its outcome.
func WithLogging(fn FetchFn) FetchFn {
	return func(url string) (string, error) {
		fmt.Printf("[fetch] GET %s\n", url)
		result, err := fn(url)
		if err != nil {
			fmt.Printf("[fetch] ERR %s: %v\n", url, err)
			return "", err
		}
		fmt.Printf("[fetch] OK  %s\n", url)
		return result, nil
	}
}
```

```go
// file: main.go
package main

import (
	"fmt"
	"example/fetcher"
)

func main() {
	fetch := fetcher.WithLogging(fetcher.WithRetry(fetcher.HTTPFetch, 3))
	body, err := fetch("https://example.com/api/data")
	if err != nil {
		fmt.Println("error:", err)
		return
	}
	fmt.Println(body)
}
```

## Common Mistake

Embedding retry and logging directly in `HTTPFetch` — the behaviors cannot be reused
independently, and every new combination needs a separate function.

```go
// ✗ subclass explosion — combined into one function; behaviors cannot be separated
func retryLoggingFetch(url string) (string, error) { // ✗ retry + logging fused
	fmt.Printf("[fetch] GET %s\n", url)              // ✗ cannot use retry without logging
	for i := 0; i < 3; i++ {
		if body, err := httpGet(url); err == nil {
			return body, nil
		}
	}
	return "", fmt.Errorf("all retries failed")
	// ✗ adding caching requires yet another combined function
}
```
