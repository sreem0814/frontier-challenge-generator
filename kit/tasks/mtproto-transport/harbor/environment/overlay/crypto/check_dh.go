package crypto

import (
	"math/big"
)

// CheckDH performs DH parameters check described in Telegram docs.
//
//	Client is expected to check whether p is a safe 2048-bit prime (meaning that both p and (p-1)/2 are prime,
//	and that 2^2047 < p < 2^2048), and that g generates a cyclic subgroup of prime order (p-1)/2, i.e.
//	is a quadratic residue mod p.
//
// The size check is p.BitLen() == 2048 (TDLib does the same). The g check is
// CheckGP. Primality uses Prime.
//
// See https://core.telegram.org/mtproto/auth_key#presenting-proof-of-work-server-authentication.
//
// See https://core.telegram.org/api/srp#checking-the-password-with-srp.
//
// See https://core.telegram.org/api/end-to-end#sending-a-request.
func CheckDH(g int, p *big.Int) error {
	return errNotImplemented
}
