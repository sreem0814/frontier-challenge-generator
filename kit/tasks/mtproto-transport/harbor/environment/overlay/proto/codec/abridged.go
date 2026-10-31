package codec

import (
	"io"

	"github.com/gotd/td/bin"
)

// AbridgedClientStart is starting bytes sent by client in Abridged mode.
//
// Note that server does not respond with it.
var AbridgedClientStart = [1]byte{0xef}

// Abridged is abridged MTProto transport.
//
// See https://core.telegram.org/mtproto/mtproto-transports#abridged
//
// Frame: the payload length divided by four, as one byte when it is below
// 127 (0x7f), otherwise the byte 0x7f followed by the length divided by four
// as 3 little-endian bytes; then the payload.
type Abridged struct{}

var (
	_ TaggedCodec = Abridged{}
)

// WriteHeader sends protocol tag (the single byte 0xef).
func (i Abridged) WriteHeader(w io.Writer) error {
	return errNotImplemented
}

// ReadHeader reads protocol tag. A byte other than 0xef is reported as
// ErrProtocolHeaderMismatch.
func (i Abridged) ReadHeader(r io.Reader) error {
	return errNotImplemented
}

// ObfuscatedTag returns protocol tag for obfuscation: 0xef repeated 4 times.
func (i Abridged) ObfuscatedTag() (r [4]byte) {
	return r
}

// Write encode to writer message from given buffer.
//
// The payload must be non-empty, at most 1<<24 bytes (16 MiB) and a multiple
// of 4 bytes long; otherwise Write returns an error and writes nothing.
func (i Abridged) Write(w io.Writer, b *bin.Buffer) error {
	return errNotImplemented
}

// Read fills buffer with received message.
//
// A 4-byte payload is a transport error and is returned as *ProtocolErr.
func (i Abridged) Read(r io.Reader, b *bin.Buffer) error {
	return errNotImplemented
}
