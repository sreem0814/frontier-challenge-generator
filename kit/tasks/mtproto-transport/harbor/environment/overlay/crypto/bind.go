package crypto

import (
	"io"

	"github.com/gotd/td/bin"
)

// BindAuthKeyInnerTypeID is TL type id for bind_auth_key_inner.
const BindAuthKeyInnerTypeID = 0x75a3f765

// BindAuthKeyInner is a temporary auth key binding payload.
//
// bind_auth_key_inner#75a3f765 nonce:long temp_auth_key_id:long
//
//	perm_auth_key_id:long temp_session_id:long expires_at:int = BindAuthKeyInner
type BindAuthKeyInner struct {
	Nonce         int64
	TempAuthKeyID int64
	PermAuthKeyID int64
	TempSessionID int64
	ExpiresAt     int
}

// TypeID returns TL type id.
func (*BindAuthKeyInner) TypeID() uint32 {
	return BindAuthKeyInnerTypeID
}

// Encode implements bin.Encoder. Encoding a nil value is an error.
func (m *BindAuthKeyInner) Encode(b *bin.Buffer) error {
	return errNotImplemented
}

// Decode implements bin.Decoder. A wrong type id or a short buffer is an
// error.
func (m *BindAuthKeyInner) Decode(b *bin.Buffer) error {
	return errNotImplemented
}

// EncryptBindMessage encrypts binding message using permanent key and MTProto v1 KDF.
//
// This helper exists specifically for auth.bindTempAuthKey flow where Telegram
// requires a legacy MTProto v1 envelope/KDF even if the transport session uses
// modern MTProto 2.0 packets for regular API traffic.
//
// The plaintext envelope is random:int128 + msg_id:long + seq_no:int (0) +
// msg_len:int + the encoded inner message; msg_key is MessageKeyV1 of that
// envelope before padding; the envelope is then padded with 0 to 15 random
// bytes to a multiple of 16 and encrypted with AES-256-IGE using KeysV1(perm key,
// msg_key). A zero permKey is an error; a nil rand means DefaultRand().
//
// See https://core.telegram.org/api/pfs#special-binding-message
//
// Result format:
//
//	perm_auth_key_id(8) + msg_key(16) + encrypted_data
func EncryptBindMessage(rand io.Reader, permKey AuthKey, msgID int64, inner *BindAuthKeyInner) ([]byte, error) {
	return nil, errNotImplemented
}
