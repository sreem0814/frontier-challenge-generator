package crypto

import (
	"github.com/gotd/td/bin"
)

// OldKeys returns (aes_key, aes_iv) pair for AES-IGE (MTProto 1.0), with
// x = 0 for Client and x = 8 for Server:
//
//	sha1_a  = SHA1(msg_key + substr(auth_key, x, 32))
//	sha1_b  = SHA1(substr(auth_key, 32+x, 16) + msg_key + substr(auth_key, 48+x, 16))
//	sha1_c  = SHA1(substr(auth_key, 64+x, 32) + msg_key)
//	sha1_d  = SHA1(msg_key + substr(auth_key, 96+x, 32))
//	aes_key = substr(sha1_a, 0, 8) + substr(sha1_b, 8, 12) + substr(sha1_c, 4, 12)
//	aes_iv  = substr(sha1_a, 8, 12) + substr(sha1_b, 0, 8) + substr(sha1_c, 16, 4) + substr(sha1_d, 0, 8)
//
// See https://core.telegram.org/mtproto/description_v1#defining-aes-key-and-initialization-vector
//
// Warning: MTProto 1.0 is deprecated. session/tdesktop uses it to read
// Telegram Desktop local storage.
func OldKeys(authKey Key, msgKey bin.Int128, mode Side) (key, iv bin.Int256) {
	return key, iv
}
