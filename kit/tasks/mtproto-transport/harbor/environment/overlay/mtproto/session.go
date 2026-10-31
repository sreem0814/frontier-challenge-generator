package mtproto

import "github.com/gotd/td/crypto"

// Session represents connection state.
type Session struct {
	ID   int64
	Key  crypto.AuthKey
	Salt int64
	// PermKey is non-zero only in PFS mode and is used for bindTempAuthKey.
	PermKey crypto.AuthKey
}
