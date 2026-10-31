// Package salts contains MTProto server salt storage.
package salts

import (
	"sync"
	"time"

	"github.com/gotd/td/mt"
)

// Salts is a simple struct store salts.
type Salts struct {
	salts    []mt.FutureSalt
	saltsMux sync.Mutex
}

// Get returns a salt that is still valid at deadline: the stored salt with
// the latest valid_until, provided valid_until > deadline (Unix seconds).
// Salts that expire at or before deadline are dropped. ok is false when no
// stored salt is valid at deadline.
func (s *Salts) Get(deadline time.Time) (int64, bool) {
	return 0, false
}

// Store adds salts, dropping duplicates (same salt value, first kept).
func (s *Salts) Store(salts []mt.FutureSalt) {}

// Reset deletes all stored salts.
func (s *Salts) Reset() {}
