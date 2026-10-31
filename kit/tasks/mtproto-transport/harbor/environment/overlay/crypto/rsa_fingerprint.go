package crypto

import (
	"crypto/rsa"
)

// RSAFingerprint returns fingerprint of RSA public key as defined in MTProto:
// the 64 lower-order bits of SHA1 of the TL serialization
// rsa_public_key n:bytes e:bytes (n and e as big-endian bytes without
// leading zeros), read as a little-endian int64 from digest bytes 12..19.
//
// See https://core.telegram.org/mtproto/auth_key#dh-exchange-initiation
func RSAFingerprint(key *rsa.PublicKey) int64 {
	return 0
}
