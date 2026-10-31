package codec

import (
	"fmt"

	"github.com/go-faster/errors"
)

const (
	// CodeAuthKeyNotFound means that specified auth key ID cannot be found by the DC.
	// Also, may be returned during key exchange.
	CodeAuthKeyNotFound = 404

	// CodeWrongDC means that current DC is wrong.
	// Usually returned by server when key exchange sends wrong DC ID.
	CodeWrongDC = 444

	// CodeTransportFlood means that too many transport connections are
	// established to the same IP in a too short lapse of time, or if any
	// of the container/service message limits are reached.
	CodeTransportFlood = 429
)

// ProtocolErr represents protocol level error.
//
// Every codec's Read reports a received 4-byte payload as a transport error:
// it returns *ProtocolErr whose Code is the negated little-endian int32 of
// that payload (the server sends -404, Read returns Code 404).
type ProtocolErr struct {
	Code int32
}

func (p ProtocolErr) Error() string {
	switch p.Code {
	case CodeAuthKeyNotFound:
		return "auth key not found"
	case CodeTransportFlood:
		return "transport flood"
	case CodeWrongDC:
		return "wrong DC"
	default:
		return fmt.Sprintf("protocol error %d", p.Code)
	}
}

// maxMessageSize is the largest payload a codec writes or accepts: 1<<24
// bytes (16 MiB). Can be bigger than 1 MiB, see
// https://github.com/gotd/td/issues/412.
//
// Write rejects an empty payload or one above this size with an error, and
// Read rejects a declared frame length that is zero, negative or above it.
const maxMessageSize = 1 << 24

// ErrProtocolHeaderMismatch means that received protocol header
// is mismatched with expected.
var ErrProtocolHeaderMismatch = errors.New("protocol header mismatch")
