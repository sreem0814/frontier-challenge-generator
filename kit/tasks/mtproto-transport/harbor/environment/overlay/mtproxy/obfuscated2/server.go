package obfuscated2

import (
	"io"
)

// Metadata represents metadata received from header.
type Metadata struct {
	Protocol [4]byte
	DC       uint16
}

// Accept creates new io.ReadWriter for server-side deobfuscation.
//
// It reads the client's 64-byte header from conn, derives the same two
// streams as the client with their roles swapped (the server decrypts with
// the client's encrypt stream and encrypts with its decrypt stream), and
// returns the protocol tag and DC id from the decrypted header. secret is
// the optional MTProxy secret, applied as in Handshake. Accept does not
// validate the protocol tag.
func Accept(conn io.ReadWriter, secret []byte) (io.ReadWriter, Metadata, error) {
	return nil, Metadata{}, errNotImplemented
}
