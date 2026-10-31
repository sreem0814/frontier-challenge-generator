package mtproto

import (
	"github.com/go-faster/errors"
)

var (
	// ErrPFSReconnectRequired is returned when connection should be recreated
	// to continue PFS flow (e.g. temp key renewal).
	ErrPFSReconnectRequired = errors.New("pfs reconnect required")
	// ErrPFSDropKeysRequired is returned when stored permanent key should be
	// dropped and generated again on the next connection attempt.
	ErrPFSDropKeysRequired = errors.New("pfs drop keys required")
)
