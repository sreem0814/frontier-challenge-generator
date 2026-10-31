package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"fmt"
	"io"
	"math/rand/v2"
	"strings"
)

// rng returns a deterministic byte stream for a case.
func rng(parts ...string) io.Reader {
	seed := sha256.Sum256([]byte(strings.Join(parts, "\x00")))
	return rand.NewChaCha8(seed)
}

// prng returns a deterministic math/rand generator for a case.
func prng(parts ...string) *rand.Rand {
	seed := sha256.Sum256([]byte("prng\x00" + strings.Join(parts, "\x00")))
	return rand.New(rand.NewChaCha8(seed))
}

func randBytes(r io.Reader, n int) []byte {
	b := make([]byte, n)
	if _, err := io.ReadFull(r, b); err != nil {
		panic(err)
	}
	return b
}

func hx(b []byte) string { return hex.EncodeToString(b) }

// h8 is a short digest used to compare large outputs.
func h8(b []byte) string {
	s := sha256.Sum256(b)
	return hex.EncodeToString(s[:8])
}

func le32(v uint32) []byte {
	var b [4]byte
	binary.LittleEndian.PutUint32(b[:], v)
	return b[:]
}

func errOr(err error, ok string) string {
	if err != nil {
		return "err"
	}
	return ok
}

func join(parts ...string) string { return strings.Join(parts, "|") }

func itoa(v any) string { return fmt.Sprint(v) }

// duplex is an in-memory, non-blocking pair of byte queues.
type duplex struct {
	in  *bytes.Buffer // read side
	out *bytes.Buffer // write side
}

func (d duplex) Read(p []byte) (int, error)  { return d.in.Read(p) }
func (d duplex) Write(p []byte) (int, error) { return d.out.Write(p) }

func newDuplex() (client, server duplex) {
	c2s, s2c := new(bytes.Buffer), new(bytes.Buffer)
	return duplex{in: s2c, out: c2s}, duplex{in: c2s, out: s2c}
}

// chunkReader returns at most n bytes per Read.
type chunkReader struct {
	r io.Reader
	n int
}

func (c chunkReader) Read(p []byte) (int, error) {
	if len(p) > c.n {
		p = p[:c.n]
	}
	return c.r.Read(p)
}

// countWriter counts bytes written.
type countWriter struct {
	buf bytes.Buffer
}

func (c *countWriter) Write(p []byte) (int, error) { return c.buf.Write(p) }
