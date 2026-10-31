package crypto

import (
	"io"
)

// GuessDataWithHash guesses data from data_with_hash.
//
// data_with_hash := SHA1(data) + data + (0-15 random bytes). It returns the
// longest data (trying 0 to 15 trailing bytes, fewest first) whose SHA1
// matches the first 20 bytes, or nil when none does or the input is not
// longer than 20 bytes.
func GuessDataWithHash(dataWithHash []byte) []byte {
	return nil
}

// DataWithHash prepends data with SHA1(data) and 0..15 random bytes so result
// length is divisible by 16.
//
// Use GuessDataWithHash(result) to obtain data.
func DataWithHash(data []byte, randomSource io.Reader) ([]byte, error) {
	return nil, errNotImplemented
}
