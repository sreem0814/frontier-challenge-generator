package crypto

import (
	"github.com/gotd/td/bin"
)

// DecryptFromBuffer decodes EncryptedMessage and decrypts it.
func (c Cipher) DecryptFromBuffer(k AuthKey, buf *bin.Buffer) (*EncryptedMessageData, error) {
	return nil, errNotImplemented
}

// Decrypt decrypts data from encrypted message using AES-IGE.
//
// Messages are decrypted with the opposite side's keys (a client Cipher
// decrypts what a server Cipher encrypted, and the reverse). Decrypt returns
// an error, and no data, when:
//   - encrypted.AuthKeyID differs from k.ID;
//   - the encrypted data length is not a multiple of 16;
//   - msg_key recomputed over the decrypted plaintext differs from
//     encrypted.MsgKey;
//   - the decrypted EncryptedMessageData does not decode (too short, or
//     MessageDataLen above the bytes available);
//   - MessageDataLen is negative or not a multiple of 4, or the padding
//     (bytes after the message data) is longer than 1024 bytes.
func (c Cipher) Decrypt(k AuthKey, encrypted *EncryptedMessage) (*EncryptedMessageData, error) {
	return nil, errNotImplemented
}
