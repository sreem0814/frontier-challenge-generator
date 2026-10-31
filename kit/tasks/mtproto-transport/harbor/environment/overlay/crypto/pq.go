package crypto

import (
	"io"
	"math/big"
)

// DecomposePQ decomposes pq into prime factors such that p < q.
//
// pq is the product of two primes and fits in 64 bits (the server's proof of
// work in "Creating an Authorization Key"). randSource may be used by a
// randomized algorithm (Pollard's rho and its variants); the factors must
// not depend on it.
//
// See https://core.telegram.org/mtproto/auth_key#dh-exchange-initiation
func DecomposePQ(pq *big.Int, randSource io.Reader) (p, q *big.Int, err error) {
	return nil, nil, errNotImplemented
}
