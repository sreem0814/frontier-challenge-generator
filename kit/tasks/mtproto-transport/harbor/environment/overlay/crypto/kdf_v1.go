package crypto

import (
	"github.com/gotd/td/bin"
)

// MessageKeyV1 computes msg_key for MTProto v1.
//
// msg_key = SHA1(plaintext)[4:20]
func MessageKeyV1(plaintext []byte) (v bin.Int128) {
	return v
}

// KeysV1 returns (aes_key, aes_iv) pair for MTProto v1.
//
// The KDF is used by auth.bindTempAuthKey encrypted_message. It is the
// OldKeys schedule with x = 0 (client side), because Telegram requires this
// exact derivation for the binding payload.
func KeysV1(authKey Key, msgKey bin.Int128) (key, iv bin.Int256) {
	return key, iv
}
