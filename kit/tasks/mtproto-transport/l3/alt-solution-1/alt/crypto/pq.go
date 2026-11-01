package crypto

// Alternative DecomposePQ: Pollard-Brent in uint64 arithmetic (math/bits), random constants from randSource.

import (
	"encoding/binary"
	"io"
	"math/big"
	"math/bits"

	"github.com/go-faster/errors"
)

func mulMod(a, b, m uint64) uint64 {
	hi, lo := bits.Mul64(a, b)
	_, rem := bits.Div64(hi, lo, m)
	return rem
}

func gcd(a, b uint64) uint64 {
	for b != 0 {
		a, b = b, a%b
	}
	return a
}

func brent(n, y, c, m uint64) uint64 {
	g, r, q := uint64(1), uint64(1), uint64(1)
	var x, ys uint64
	f := func(v uint64) uint64 { s, carry := bits.Add64(mulMod(v, v, n), c, 0); if carry != 0 || s >= n { s -= n }; return s }
	for g == 1 {
		x = y
		for i := uint64(0); i < r; i++ {
			y = f(y)
		}
		for k := uint64(0); k < r && g == 1; k += m {
			ys = y
			for i := uint64(0); i < m && i < r-k; i++ {
				y = f(y)
				d := x - y
				if x < y {
					d = y - x
				}
				q = mulMod(q, d, n)
			}
			g = gcd(q, n)
		}
		r *= 2
	}
	if g == n {
		for {
			ys = f(ys)
			d := x - ys
			if x < ys {
				d = ys - x
			}
			g = gcd(d, n)
			if g > 1 {
				break
			}
		}
	}
	return g
}

// DecomposePQ decomposes pq into prime factors such that p < q.
func DecomposePQ(pq *big.Int, randSource io.Reader) (p, q *big.Int, err error) {
	if !pq.IsUint64() || pq.Uint64() < 4 || pq.ProbablyPrime(20) {
		return nil, nil, errors.New("pq is not a product of two primes below 2^64")
	}
	n := pq.Uint64()
	var f uint64
	if n%2 == 0 {
		f = 2
	}
	for f == 0 || f == n {
		var buf [16]byte
		if _, err := io.ReadFull(randSource, buf[:]); err != nil {
			return nil, nil, err
		}
		y := binary.LittleEndian.Uint64(buf[:8])%(n-1) + 1
		c := binary.LittleEndian.Uint64(buf[8:])%(n-1) + 1
		f = brent(n, y, c, 128)
	}
	a, b := f, n/f
	if a > b {
		a, b = b, a
	}
	return new(big.Int).SetUint64(a), new(big.Int).SetUint64(b), nil
}
