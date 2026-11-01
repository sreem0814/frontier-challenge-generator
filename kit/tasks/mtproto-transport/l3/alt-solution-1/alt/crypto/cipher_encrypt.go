package crypto

// Alternative Encrypt: a different padding policy (12..27 bytes plus 0..59 random 16-byte blocks drawn from two
// random bytes, padding bytes read before the length draw) and a separate output buffer.

import (
	"crypto/aes"
	"encoding/binary"
	"io"

	"github.com/gotd/ige"

	"github.com/gotd/td/bin"
)

// Encrypt encrypts EncryptedMessageData using AES-IGE to given buffer.
func (c Cipher) Encrypt(key AuthKey, data EncryptedMessageData, b *bin.Buffer) error {
	plain := new(bin.Buffer)
	if err := data.EncodeWithoutCopy(plain); err != nil {
		return err
	}
	n := len(plain.Buf)
	pool := make([]byte, 12+15+59*16)
	if _, err := io.ReadFull(c.rand, pool); err != nil {
		return err
	}
	var r [2]byte
	if _, err := io.ReadFull(c.rand, r[:]); err != nil {
		return err
	}
	pad := 12 + (16-(n+12)%16)%16 + int(binary.LittleEndian.Uint16(r[:])%60)*16
	plaintext := append(plain.Buf, pool[:pad]...)

	msgKey := MessageKey(key.Value, plaintext, c.encryptSide)
	k, iv := Keys(key.Value, msgKey, c.encryptSide)
	block, err := aes.NewCipher(k[:])
	if err != nil {
		return err
	}
	enc := make([]byte, len(plaintext))
	ige.EncryptBlocks(block, iv[:], enc, plaintext)
	b.Reset()
	b.Put(key.ID[:])
	b.PutInt128(msgKey)
	b.Put(enc)
	return nil
}
