package crypto

import (
	"crypto/rsa"
	"io"
)

// RSAPad encrypts given data with RSA, prefixing with a hash (RSA_PAD).
//
// Data longer than 144 bytes is an error. The result is exactly 256 bytes.
// DecodeRSAPad(result, private key) must return the 192-byte
// data_with_padding whose first len(data) bytes are data.
//
// See https://core.telegram.org/mtproto/auth_key#presenting-proof-of-work-server-authentication.
func RSAPad(data []byte, key *rsa.PublicKey, randomSource io.Reader) ([]byte, error) {
	return nil, errNotImplemented
}

// DecodeRSAPad implements server-side decoder of RSAPad.
//
// It returns data_with_padding (192 bytes: data followed by the random
// padding), or an error when the RSA-decrypted value does not fit in 256
// bytes or the SHA256(temp_key + data_with_padding) check fails.
func DecodeRSAPad(data []byte, key *rsa.PrivateKey) ([]byte, error) {
	return nil, errNotImplemented
}
