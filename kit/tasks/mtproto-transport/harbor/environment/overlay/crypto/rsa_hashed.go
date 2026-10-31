package crypto

import (
	"crypto/rsa"
	"io"
)

// RSAEncryptHashed encrypts given data with RSA, prefixing with a hash.
//
// data_with_hash := SHA1(data) + data + (any random bytes), 255 bytes in
// total, is raised to e mod n; the result is exactly 256 big-endian bytes.
// Data longer than 235 bytes is an error.
func RSAEncryptHashed(data []byte, key *rsa.PublicKey, randomSource io.Reader) ([]byte, error) {
	return nil, errNotImplemented
}

// RSADecryptHashed decrypts given data with RSA.
//
// It returns the longest prefix of the 235 bytes after the hash whose SHA1
// equals the hash, and an error if the decrypted value does not fit in 255
// bytes or no prefix matches.
func RSADecryptHashed(data []byte, key *rsa.PrivateKey) ([]byte, error) {
	return nil, errNotImplemented
}
