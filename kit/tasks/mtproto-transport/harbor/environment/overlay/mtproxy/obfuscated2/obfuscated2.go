package obfuscated2

import (
	"io"

	"github.com/go-faster/errors"

	"github.com/gotd/td/mtproxy"
)

// errNotImplemented is returned until the obfuscation layer is rebuilt.
var errNotImplemented = errors.New("obfuscated2: not implemented")

// Obfuscated2 implements obfuscated2 obfuscation protocol.
//
// See https://core.telegram.org/mtproto/mtproto-transports#transport-obfuscation
//
// The client sends a 64-byte header, then every byte in both directions goes
// through AES-256-CTR. The header is built from 64 random bytes "init":
//
//   - init is redrawn (all 64 bytes again) while init[0] is 0xef, the first
//     little-endian uint32 is one of 0x44414548 ("HEAD"), 0x54534f50
//     ("POST"), 0x20544547 ("GET "), 0x4954504f ("OPTI"), 0x02010316,
//     0xdddddddd or 0xeeeeeeee, or the second little-endian uint32 is zero;
//   - the encrypt key is init[8:40] and its IV init[40:56]; the decrypt key
//     and IV are the first 32 and the next 16 bytes of init[8:56] reversed;
//   - with a secret (at least 16 bytes, of which the first 16 are used) each
//     key becomes SHA256(key + secret); a secret of 1 to 15 bytes is an
//     error;
//   - init[56:60] is the protocol tag and init[60:62] the DC id as a
//     little-endian int16;
//   - the header is init[0:56] followed by bytes 56..63 of init encrypted
//     with the encrypt stream. Those 64 bytes stay consumed, so the first
//     payload byte is encrypted with keystream byte 64.
type Obfuscated2 struct {
	rand io.Reader
	conn io.ReadWriter
}

// NewObfuscated2 creates new Obfuscated2.
//
// r is the random source for Handshake, conn the underlying connection.
func NewObfuscated2(r io.Reader, conn io.ReadWriter) *Obfuscated2 {
	return &Obfuscated2{
		rand: r,
		conn: conn,
	}
}

// Handshake sends obfuscated2 header.
//
// protocol is the codec tag (codec.TaggedCodec.ObfuscatedTag), dc the DC id
// and s.Secret the optional MTProxy secret.
func (o *Obfuscated2) Handshake(protocol [4]byte, dc int, s mtproxy.Secret) error {
	return errNotImplemented
}

// Write implements io.Writer: it encrypts b and writes it to the connection.
// It does not modify b.
func (o *Obfuscated2) Write(b []byte) (n int, err error) {
	return 0, errNotImplemented
}

// Read implements io.Reader: it reads from the connection and decrypts the
// bytes actually read (a short read advances the stream only by n bytes).
func (o *Obfuscated2) Read(b []byte) (int, error) {
	return 0, errNotImplemented
}
