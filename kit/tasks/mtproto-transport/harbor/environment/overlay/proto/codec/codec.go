package codec

import (
	"io"

	"github.com/go-faster/errors"

	"github.com/gotd/td/bin"
)

// Codec is MTProto transport protocol encoding abstraction.
type Codec interface {
	// WriteHeader sends protocol tag if needed.
	WriteHeader(w io.Writer) error
	// ReadHeader reads protocol tag if needed.
	ReadHeader(r io.Reader) error
	// Write encode to writer message from given buffer.
	Write(w io.Writer, b *bin.Buffer) error
	// Read fills buffer with received message.
	Read(r io.Reader, b *bin.Buffer) error
}

// TaggedCodec is codec with protocol tag.
type TaggedCodec interface {
	Codec
	// ObfuscatedTag returns protocol tag for obfuscation.
	ObfuscatedTag() [4]byte
}

// errNotImplemented is returned by every codec until the transports are rebuilt.
var errNotImplemented = errors.New("codec: not implemented")
