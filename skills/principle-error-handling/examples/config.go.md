# Error Handling — Go — Config Parse & Validate

## Problem

Go surfaces errors as values, not exceptions. Each tier (IO, parse, validation) returns
a distinct `error` wrapped with `%w` so callers can inspect cause chains with
`errors.Is`/`errors.As` while still reading a human-friendly message at every layer.

## Implementation

```go
// file: config.go
package config

import (
	"bufio"
	"fmt"
	"os"
	"strconv"
	"strings"
)

type Config struct{ Host string; Port int }

type ConfigError struct{ Code, Msg string; Err error }

func (e *ConfigError) Error() string  { return fmt.Sprintf("[%s] %s", e.Code, e.Msg) }
func (e *ConfigError) Unwrap() error  { return e.Err }

func Parse(path string) (Config, error) {
	f, err := os.Open(path)
	if err != nil {
		return Config{}, fmt.Errorf("reading config: %w", err)
	}
	defer f.Close()

	kv := map[string]string{}
	sc := bufio.NewScanner(f)
	for n := 1; sc.Scan(); n++ {
		line := strings.TrimSpace(sc.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		parts := strings.SplitN(line, "=", 2)
		if len(parts) != 2 || strings.TrimSpace(parts[0]) == "" {
			return Config{}, fmt.Errorf("parsing line %d: %w", n,
				&ConfigError{Code: "PARSE", Msg: "malformed line, expected key=value"})
		}
		kv[strings.TrimSpace(parts[0])] = strings.TrimSpace(parts[1])
	}

	return validate(kv)
}

func validate(kv map[string]string) (Config, error) {
	host, ok := kv["host"]
	if !ok || host == "" {
		return Config{}, fmt.Errorf("validating config: %w",
			&ConfigError{Code: "VALIDATION", Msg: "missing required key: host"})
	}
	portStr, ok := kv["port"]
	if !ok {
		return Config{}, fmt.Errorf("validating config: %w",
			&ConfigError{Code: "VALIDATION", Msg: "missing required key: port"})
	}
	port, err := strconv.Atoi(portStr)
	if err != nil {
		return Config{}, fmt.Errorf("validating config: %w",
			&ConfigError{Code: "VALIDATION", Msg: "port must be an integer", Err: err})
	}
	if port < 1 || port > 65535 {
		return Config{}, fmt.Errorf("validating config: %w",
			&ConfigError{Code: "VALIDATION", Msg: "port out of range 1-65535"})
	}
	return Config{Host: host, Port: port}, nil
}
```

```go
// file: main.go
package main

import (
	"errors"
	"fmt"
	"example/config"
)

func main() {
	cfg, err := config.Parse("app.conf")
	if err != nil {
		var ce *config.ConfigError
		if errors.As(err, &ce) {
			fmt.Println("config error:", ce.Code, "-", ce.Msg)
		} else {
			fmt.Println("io error:", err)
		}
		return
	}
	fmt.Printf("host=%s port=%d\n", cfg.Host, cfg.Port)
}
```

## Common Mistake

Returning `nil` instead of the error — silently drops failures every caller depends on.

```go
if err != nil {
    return Config{}, nil // ✗ error swallowed; caller sees a zero Config, no signal
}
```
