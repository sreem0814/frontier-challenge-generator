package crypto

import (
	"github.com/gotd/td/bin"
)

// EncryptedMessageData is stored in EncryptedMessage.EncryptedData.
//
// Wire layout: salt (long), session_id (long), message_id (long), seq_no
// (int), message_data_length (int), then message data and padding.
type EncryptedMessageData struct {
	Salt                   int64
	SessionID              int64
	MessageID              int64
	SeqNo                  int32
	MessageDataLen         int32
	MessageDataWithPadding []byte

	// Message to encode to MessageDataWithPadding.
	// Needed to prevent unnecessary allocations in EncodeWithoutCopy.
	Message bin.Encoder
}

// Encode implements bin.Encoder. It writes the fields as they are
// (MessageDataLen is not recomputed) followed by MessageDataWithPadding.
func (e EncryptedMessageData) Encode(b *bin.Buffer) error {
	return errNotImplemented
}

// EncodeWithoutCopy is like Encode, but tries to encode Message and uses only one buffer
// to encode. If Message is nil, fallbacks to Encode. When Message is set,
// message_data_length is the encoded length of Message and
// MessageDataLen/MessageDataWithPadding are ignored.
func (e EncryptedMessageData) EncodeWithoutCopy(b *bin.Buffer) error {
	return errNotImplemented
}

// Decode implements bin.Decoder. The rest of the buffer after the 32-byte
// header becomes MessageDataWithPadding (copied); a MessageDataLen larger
// than that is an error.
func (e *EncryptedMessageData) Decode(b *bin.Buffer) error {
	return errNotImplemented
}

// DecodeWithoutCopy is like Decode, but MessageDataWithPadding references to given buffer instead of
// copying.
func (e *EncryptedMessageData) DecodeWithoutCopy(b *bin.Buffer) error {
	return errNotImplemented
}

// Data returns message data without padding: the first MessageDataLen bytes
// of MessageDataWithPadding.
func (e *EncryptedMessageData) Data() []byte {
	return nil
}
