package crypto

import (
	"github.com/gotd/td/bin"
)

// ServerSalt computes server salt: the first 8 bytes of new_nonce XOR the
// first 8 bytes of server_nonce, read as a little-endian int64.
func ServerSalt(newNonce bin.Int256, serverNonce bin.Int128) (salt int64) {
	return 0
}
