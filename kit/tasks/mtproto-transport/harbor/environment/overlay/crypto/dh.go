package crypto

import (
	"math/big"
)

// CheckDHParams checks that g_a, g_b and g params meet key exchange conditions:
// 1 < g, g_a, g_b < dh_prime - 1, and 2^(2048-64) < g_a, g_b < dh_prime - 2^(2048-64).
//
// https://core.telegram.org/mtproto/auth_key#dh-key-exchange-complete
func CheckDHParams(dhPrime, g, gA, gB *big.Int) error {
	return errNotImplemented
}

// InRange checks whether x is in (min, max) range, i.e. min < x < max.
func InRange(x, min, max *big.Int) bool {
	return false
}
