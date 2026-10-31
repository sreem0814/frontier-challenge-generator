package crypto

import (
	"github.com/gotd/td/bin"
)

// Side on which encryption is performed.
type Side byte

const (
	// Client side of encryption (e.g. messages from client).
	Client Side = 0
	// Server side of encryption (e.g. RPC responses).
	Server Side = 1
)

// DecryptSide returns Side for decryption.
func (s Side) DecryptSide() Side {
	return s ^ 1 // flips bit, so 0 becomes 1, 1 becomes 0
}

// Keys returns (aes_key, aes_iv) pair for AES-IGE (MTProto 2.0), with
// x = 0 for Client and x = 8 for Server:
//
//	sha256_a = SHA256(msg_key + substr(auth_key, x, 36))
//	sha256_b = SHA256(substr(auth_key, 40+x, 36) + msg_key)
//	aes_key  = substr(sha256_a, 0, 8) + substr(sha256_b, 8, 16) + substr(sha256_a, 24, 8)
//	aes_iv   = substr(sha256_b, 0, 8) + substr(sha256_a, 8, 16) + substr(sha256_b, 24, 8)
//
// See https://core.telegram.org/mtproto/description#defining-aes-key-and-initialization-vector
func Keys(authKey Key, msgKey bin.Int128, mode Side) (key, iv bin.Int256) {
	return key, iv
}

// MessageKey computes message key for provided auth_key and padded payload:
//
//	msg_key_large = SHA256(substr(auth_key, 88+x, 32) + plaintext + random_padding)
//	msg_key       = substr(msg_key_large, 8, 16)
//
// with x = 0 for Client and x = 8 for Server.
func MessageKey(authKey Key, plaintextPadded []byte, mode Side) bin.Int128 {
	return bin.Int128{}
}
