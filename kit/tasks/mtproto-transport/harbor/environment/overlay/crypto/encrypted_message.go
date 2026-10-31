package crypto

import "github.com/gotd/td/bin"

// EncryptedMessage of protocol.
//
// Wire layout: auth_key_id (8 bytes), msg_key (int128), encrypted data (the
// rest of the buffer).
type EncryptedMessage struct {
	AuthKeyID [8]byte
	MsgKey    bin.Int128

	EncryptedData []byte
}

// Decode implements bin.Decoder. It consumes the whole buffer; fewer than
// 24 bytes is an error.
func (e *EncryptedMessage) Decode(b *bin.Buffer) error {
	return errNotImplemented
}

// DecodeWithoutCopy is like Decode, but EncryptedData references to given buffer instead of
// copying.
func (e *EncryptedMessage) DecodeWithoutCopy(b *bin.Buffer) error {
	return errNotImplemented
}

// Encode implements bin.Encoder.
func (e EncryptedMessage) Encode(b *bin.Buffer) error {
	return errNotImplemented
}
