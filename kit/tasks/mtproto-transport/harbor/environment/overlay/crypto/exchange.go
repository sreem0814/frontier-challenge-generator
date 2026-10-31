package crypto

import (
	"io"

	"github.com/gotd/td/bin"
)

// DecryptExchangeAnswer decrypts messages created during key exchange
// (server_DH_inner_data and client_DH_inner_data): AES-256-IGE with the
// temporary key and IV, then GuessDataWithHash. Data whose length is not a
// multiple of 16 is an error.
func DecryptExchangeAnswer(data, key, iv []byte) (dst []byte, err error) {
	return nil, errNotImplemented
}

// EncryptExchangeAnswer encrypts messages created during key exchange:
// DataWithHash(answer, rand), then AES-256-IGE with key and iv.
func EncryptExchangeAnswer(rand io.Reader, answer, key, iv []byte) (dst []byte, err error) {
	return nil, errNotImplemented
}

// NonceHash1 computes new_nonce_hash1: the 128 lower-order bits of
// SHA1(new_nonce + 0x01 + auth_key_aux_hash), i.e. bytes 4..19 of the digest.
//
// See https://core.telegram.org/mtproto/auth_key#dh-key-exchange-complete.
func NonceHash1(newNonce bin.Int256, key Key) (r bin.Int128) {
	return r
}
