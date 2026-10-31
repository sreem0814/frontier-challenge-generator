package codec

import (
	"io"

	"github.com/gotd/td/bin"
)

// PaddedIntermediateClientStart is starting bytes sent by client in Padded intermediate mode.
//
// Note that server does not respond with it.
var PaddedIntermediateClientStart = [4]byte{0xdd, 0xdd, 0xdd, 0xdd}

// PaddedIntermediate is padded intermediate MTProto transport.
//
// See https://core.telegram.org/mtproto/mtproto-transports#padded-intermediate
//
// Frame: like Intermediate, but the sender appends 0 to 3 random bytes to the
// (4-byte aligned) payload and the length field counts them. The receiver
// drops the last (length mod 4) bytes of the frame.
type PaddedIntermediate struct{}

var (
	_ TaggedCodec = PaddedIntermediate{}
)

// WriteHeader sends protocol tag (0xdddddddd).
func (i PaddedIntermediate) WriteHeader(w io.Writer) error {
	return errNotImplemented
}

// ReadHeader reads protocol tag. Any other 4 bytes are reported as
// ErrProtocolHeaderMismatch.
func (i PaddedIntermediate) ReadHeader(r io.Reader) error {
	return errNotImplemented
}

// ObfuscatedTag returns protocol tag for obfuscation (0xdddddddd).
func (i PaddedIntermediate) ObfuscatedTag() (r [4]byte) {
	return r
}

// Write encode to writer message from given buffer.
//
// The payload must be non-empty, at most 1<<24 bytes (16 MiB) and a multiple
// of 4 bytes long; otherwise Write returns an error and writes nothing. The
// random padding comes from crypto.DefaultRand().
func (i PaddedIntermediate) Write(w io.Writer, b *bin.Buffer) error {
	return errNotImplemented
}

// Read fills buffer with received message, without the padding.
//
// A declared length of zero, below zero or above 1<<24 is an error.
// A 4-byte payload is a transport error and is returned as *ProtocolErr.
func (i PaddedIntermediate) Read(r io.Reader, b *bin.Buffer) error {
	return errNotImplemented
}
