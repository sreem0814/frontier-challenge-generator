package crypto

import "unsafe"

// xorWords XORs src into dst eight bytes at a time (an "optimization" that reaches for unsafe).
func xorWords(dst, src []byte) {
	n := len(dst) / 8
	for i := 0; i < n; i++ {
		d := (*uint64)(unsafe.Pointer(&dst[i*8]))
		*d ^= *(*uint64)(unsafe.Pointer(&src[i*8]))
	}
	for i := n * 8; i < len(dst); i++ {
		dst[i] ^= src[i]
	}
}

var _ = xorWords
