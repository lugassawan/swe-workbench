# Error Handling — Go — HTTP Fetch with Retry

## Problem

Go models errors as values, so callers classify them with `errors.Is` before deciding
whether to retry. Sentinel errors (`ErrTimeout`, `ErrExhausted`) make transient-vs-permanent
branching explicit, and injecting a `Transport` interface decouples the retry loop from real HTTP.

## Implementation

```go
// file: transport.go
package fetch

import ("errors"; "fmt")

var ErrTimeout   = errors.New("timeout")
var ErrExhausted = errors.New("exhausted all retries")

type Response struct{ Status int; Body string }

type PermanentError struct{ Status int }
func (e *PermanentError) Error() string { return fmt.Sprintf("permanent %d", e.Status) }

type Transport interface {
	Fetch(url string) (*Response, error)
}

type FakeTransport struct{ Attempt int }

func (f *FakeTransport) Fetch(url string) (*Response, error) {
	if url == "/not-found" { return nil, &PermanentError{Status: 404} }
	defer func() { f.Attempt++ }()
	if f.Attempt < 2 { return nil, ErrTimeout }
	return &Response{Status: 200, Body: "OK"}, nil
}
```

```go
// file: fetch.go
package fetch

import ("errors"; "fmt"; "math/rand") // rand v1 top-level fns deprecated in Go 1.20; use math/rand/v2 in real code

func isTransient(resp *Response, err error) bool {
	var pe *PermanentError
	if errors.As(err, &pe) { return false }
	if errors.Is(err, ErrTimeout) { return true }
	return resp != nil && resp.Status >= 500
}

// FetchWithRetry retries transient failures with exponential backoff + jitter.
// timeoutMs is a parameter; real impl uses context.WithTimeout.
func FetchWithRetry(t Transport, url string, maxRetries, timeoutMs int) (*Response, error) {
	const baseMs = 100
	for attempt := 0; attempt < maxRetries; attempt++ {
		resp, err := t.Fetch(url)
		if err == nil && resp.Status < 400 { return resp, nil }
		if !isTransient(resp, err) {
			if err != nil { return nil, fmt.Errorf("permanent: %w", err) }
			return resp, nil
		}
		delay := float64(baseMs) * float64(1<<attempt) * (rand.Float64() + 0.5)
		_ = delay // sleep(delay) — real impl: time.Sleep(time.Duration(delay)*time.Millisecond)
	}
	return nil, fmt.Errorf("%w after %d attempts on %s", ErrExhausted, maxRetries, url)
}
```

```go
// file: main.go
package main

import ("errors"; "fmt"; "example/fetch")

func main() {
	t := &fetch.FakeTransport{}
	// transient → success (attempts 0,1 timeout; attempt 2 succeeds)
	resp, err := fetch.FetchWithRetry(t, "/api/data", 5, 1000)
	if err != nil {
		fmt.Println("error:", err)
	} else {
		fmt.Printf("status=%d body=%s\n", resp.Status, resp.Body)
	}

	// permanent → fail immediately
	t2 := &fetch.FakeTransport{}
	resp, err = fetch.FetchWithRetry(t2, "/not-found", 5, 1000)
	if err != nil {
		var pe *fetch.PermanentError
		if errors.As(err, &pe) { fmt.Printf("permanent %d — no retries\n", pe.Status) } else { fmt.Println("error:", err) }
	} else {
		fmt.Printf("unexpected ok: status=%d\n", resp.Status)
	}
}
```

## Common Mistake

Retrying every error — including `PermanentError` and transient ones — indiscriminately
wastes the retry budget and hammers the server on unrecoverable failures.

```go
for i := 0; i < maxRetries; i++ {
	resp, err := t.Fetch(url) // ✗ no classify — retries PermanentError and transient errors alike
	if err != nil {
		continue               // ✗ no backoff — tight loop
	}
	return resp, nil
}
```
