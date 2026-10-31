// Command zgrade runs the behavioural cases against the packages in this
// module tree and writes one JSON line per case: {"i":index,"id":...,"out":...}.
//
// It is built and run by tests/collect.py in a scratch copy of the module.
// Cases are numbered; -from N resumes after a case that hung (the collector
// kills the process and restarts it from the next case).
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"runtime/debug"
	"time"
)

type tcase struct {
	id      string
	fn      func() string
	timeout time.Duration
}

var registry []tcase

func add(id string, fn func() string) {
	registry = append(registry, tcase{id: id, fn: fn, timeout: 20 * time.Second})
}

func addT(id string, timeout time.Duration, fn func() string) {
	registry = append(registry, tcase{id: id, fn: fn, timeout: timeout})
}

func main() {
	out := flag.String("out", "", "output file (appended)")
	from := flag.Int("from", 0, "first case index")
	list := flag.Bool("list", false, "print case ids and exit")
	flag.Parse()

	registerAll()

	if *list {
		for i, c := range registry {
			fmt.Printf("%d %s\n", i, c.id)
		}
		return
	}
	f, err := os.OpenFile(*out, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
	if err != nil {
		fmt.Fprintln(os.Stderr, "open:", err)
		os.Exit(2)
	}
	emit := func(i int, id, res string) {
		line, _ := json.Marshal(map[string]any{"i": i, "id": id, "out": res})
		_, _ = f.Write(append(line, '\n'))
	}
	for i := *from; i < len(registry); i++ {
		c := registry[i]
		done := make(chan string, 1)
		go func() {
			defer func() {
				if r := recover(); r != nil {
					done <- "PANIC"
				}
			}()
			done <- c.fn()
		}()
		select {
		case res := <-done:
			emit(i, c.id, res)
		case <-time.After(c.timeout):
			emit(i, c.id, "TIMEOUT")
			_ = f.Sync()
			os.Exit(3)
		}
		debug.FreeOSMemory()
	}
	_ = f.Sync()
	_ = f.Close()
}

func registerAll() {
	registerCodec()
	registerObfs()
	registerMsg()
	registerHandshake()
	registerKex()
	registerSess()
}
