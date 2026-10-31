package crypto

import (
	"github.com/gotd/td/bin"
)

// Encrypt encrypts EncryptedMessageData using AES-IGE to given buffer.
//
// b is reset and receives the encoded EncryptedMessage: auth_key_id, msg_key,
// then the encrypted data. The plaintext is data encoded with
// EncodeWithoutCopy followed by random padding read from the Cipher's random
// source: at least 12 bytes and at most 1024, with the total plaintext length
// a multiple of 16. msg_key is MessageKey(key.Value, plaintext with padding,
// side) and the AES key and IV are Keys(key.Value, msg_key, side), where side
// is the Cipher's own side (Client for NewClientCipher, Server for
// NewServerCipher).
func (c Cipher) Encrypt(key AuthKey, data EncryptedMessageData, b *bin.Buffer) error {
	return errNotImplemented
}
