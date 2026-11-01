package obfuscated2

import (
	"crypto/aes"
	"crypto/cipher"
	"encoding/binary"
	"io"
)

func createCTR(key, iv []byte) (cipher.Stream, error) {
	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, err
	}
	return cipher.NewCTR(block, iv), nil
}

func getDecryptInit(init []byte) (initRev [48]byte) {
	copy(initRev[:], init[8:56])
	// https://github.com/golang/go/wiki/SliceTricks#reversing
	for left, right := 0, len(initRev)-1; left < right; left, right = left+1, right-1 {
		initRev[left], initRev[right] = initRev[right], initRev[left]
	}

	return
}

// function from https://core.telegram.org/mtproto/mtproto-transports#transport-obfuscation
func generateInit(randSource io.Reader) (init [64]byte, err error) {
	// Alternative draw: 56 bytes, then the last 8, both redrawn while the start is reserved.
	for {
		if _, err = io.ReadFull(randSource, init[:56]); err != nil {
			return [64]byte{}, err
		}
		if _, err = io.ReadFull(randSource, init[56:]); err != nil {
			return [64]byte{}, err
		}
		first := binary.LittleEndian.Uint32(init[0:4])
		switch {
		case init[0] == 0xef,
			first == 0x44414548, first == 0x54534f50, first == 0x20544547, first == 0x4954504f,
			first == 0x02010316, first == 0xdddddddd, first == 0xeeeeeeee,
			binary.LittleEndian.Uint32(init[4:8]) == 0:
			continue
		}
		return init, nil
	}
}
