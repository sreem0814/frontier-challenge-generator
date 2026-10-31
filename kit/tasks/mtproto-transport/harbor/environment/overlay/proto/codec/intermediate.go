package codec

import (
	"io"

	"github.com/gotd/td/bin"
)

// IntermediateClientStart is starting bytes sent by client in Intermediate mode.
//
// Note that server does not respond with it.
var IntermediateClientStart = [4]byte{0xee, 0xee, 0xee, 0xee}

// Intermediate is intermediate MTProto transport.
//
// See https://core.telegram.org/mtproto/mtproto-transports#intermediate
//
// Frame: the payload length as a 4-byte little-endian integer, then the
// payload.
type Intermediate struct{}

var (
	_ TaggedCodec = Intermediate{}
)

// WriteHeader sends protocol tag (0xeeeeeeee).
func (i Intermediate) WriteHeader(w io.Writer) (err error) {
	return errNotImplemented
}

// ReadHeader reads protocol tag. Any other 4 bytes are reported as
// ErrProtocolHeaderMismatch.
func (i Intermediate) ReadHeader(r io.Reader) (err error) {
	return errNotImplemented
}

// ObfuscatedTag returns protocol tag for obfuscation (0xeeeeeeee).
func (i Intermediate) ObfuscatedTag() (r [4]byte) {
	return r
}

// Write encode to writer message from given buffer.
//
// The payload must be non-empty, at most 1<<24 bytes (16 MiB) and a multiple
// of 4 bytes long; otherwise Write returns an error and writes nothing.
func (i Intermediate) Write(w io.Writer, b *bin.Buffer) error {
	return errNotImplemented
}

// Read fills buffer with received message.
//
// A declared length of zero, below zero or above 1<<24 is an error.
// A 4-byte payload is a transport error and is returned as *ProtocolErr.
func (i Intermediate) Read(r io.Reader, b *bin.Buffer) error {
	return errNotImplemented
}
