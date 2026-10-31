package crypto

import (
	"crypto/rsa"
)

// RSAKeyBits is RSA key size.
//
// Can be used as rsa.GenerateKey(src, RSAKeyBits).
const RSAKeyBits = 2048

// RSAPublicDecrypt recovers the message digest from the raw signature
// using the signer's RSA public key: sig^e mod n, as big-endian bytes without
// leading zeros.
//
// A signature whose length differs from the key size in bytes (or a key
// smaller than 11 bytes) is rejected with rsa.ErrVerification.
//
// See also OpenSSL's RSA_public_decrypt with RSA_NO_PADDING.
func RSAPublicDecrypt(pub *rsa.PublicKey, sig []byte) ([]byte, error) {
	return nil, errNotImplemented
}
