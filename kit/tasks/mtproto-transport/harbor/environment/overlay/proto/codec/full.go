package codec

import (
	"io"

	"github.com/gotd/td/bin"
)

// Full is full MTProto transport.
//
// See https://core.telegram.org/mtproto/mtproto-transports#full
//
// Frame: total length (4 + 4 + len(payload) + 4) as a 4-byte little-endian
// integer, the sequence number as a 4-byte little-endian integer, the
// payload, then CRC32 (IEEE) of the length, sequence number and payload as a
// 4-byte little-endian integer. Full has no protocol tag.
//
// Sequence numbers are counted separately for writing and reading, per Full
// value: the first frame written is numbered 0, the next 1, and so on; Read
// expects 0, 1, 2... in the same way. Use a pointer (&Full{}).
type Full struct {
	wSeqNo int64
	rSeqNo int64
}

// WriteHeader is a no-op: Full has no protocol tag.
func (i *Full) WriteHeader(w io.Writer) (err error) {
	return errNotImplemented
}

// ReadHeader is a no-op: Full has no protocol tag.
func (i *Full) ReadHeader(r io.Reader) (err error) {
	return errNotImplemented
}

// Write encode to writer message from given buffer.
//
// The payload must be non-empty and at most 1<<24 bytes (16 MiB) long; no
// alignment is required.
func (i *Full) Write(w io.Writer, b *bin.Buffer) error {
	return errNotImplemented
}

// Read fills buffer with received message.
//
// A sequence number other than the expected one, or a CRC mismatch, is an
// error. A 4-byte payload is a transport error and is returned as
// *ProtocolErr.
func (i *Full) Read(r io.Reader, b *bin.Buffer) error {
	return errNotImplemented
}
