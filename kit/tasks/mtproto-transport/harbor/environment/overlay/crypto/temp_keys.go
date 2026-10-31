package crypto

import (
	"math/big"
)

// TempAESKeys returns tmp_aes_key and tmp_aes_iv based on new_nonce and
// server_nonce as defined in "Creating an Authorization Key":
//
//	tmp_aes_key := SHA1(new_nonce + server_nonce) + substr(SHA1(server_nonce + new_nonce), 0, 12)
//	tmp_aes_iv  := substr(SHA1(server_nonce + new_nonce), 12, 8) + SHA1(new_nonce + new_nonce) + substr(new_nonce, 0, 4)
//
// new_nonce (int256) and server_nonce (int128) are fixed-length byte strings
// of 32 and 16 bytes and are hashed at their full length, so the *big.Int
// arguments are serialized back to exactly 32 and 16 big-endian bytes
// (leading zero bytes kept).
func TempAESKeys(newNonce, serverNonce *big.Int) (key, iv []byte) {
	return nil, nil
}
