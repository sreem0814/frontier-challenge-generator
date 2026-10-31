package main

import (
	"bufio"
	crand "crypto/rand"
	"bytes"
	"crypto/rsa"
	"crypto/x509"
	"embed"
	"encoding/pem"
	"errors"
	"fmt"
	"math/big"
	"strings"
	"time"

	"github.com/gotd/td/bin"
	agcrypto "github.com/gotd/td/crypto"
	refcrypto "github.com/gotd/td/internal/zref/crypto"
)

//go:embed data
var dataFS embed.FS

var (
	privKeys []*rsa.PrivateKey
	tgKeys   []*rsa.PublicKey
	primes   = map[string]*big.Int{}
)

func loadData() {
	if privKeys != nil {
		return
	}
	for i := 1; i <= 6; i++ {
		b, err := dataFS.ReadFile(fmt.Sprintf("data/rsa%d.pem", i))
		if err != nil {
			panic(err)
		}
		blk, _ := pem.Decode(b)
		k, err := x509.ParsePKCS1PrivateKey(blk.Bytes)
		if err != nil {
			panic(err)
		}
		privKeys = append(privKeys, k)
	}
	b, err := dataFS.ReadFile("data/telegram_public_keys.pem")
	if err != nil {
		panic(err)
	}
	tg, err := refcrypto.ParseRSAPublicKeys(b)
	if err != nil {
		panic(err)
	}
	tgKeys = tg
	pf, err := dataFS.ReadFile("data/primes.txt")
	if err != nil {
		panic(err)
	}
	sc := bufio.NewScanner(bytes.NewReader(pf))
	sc.Buffer(make([]byte, 1<<16), 1<<16)
	n := 0
	for sc.Scan() {
		f := strings.Fields(sc.Text())
		if len(f) != 2 {
			continue
		}
		v, ok := new(big.Int).SetString(f[1], 16)
		if !ok {
			panic("bad prime")
		}
		name := f[0]
		if _, dup := primes[name]; dup {
			name = fmt.Sprintf("%s%d", name, n)
		}
		primes[name] = v
		n++
	}
	primes["telegram"] = hexInt("C71CAEB9C6B1C9048E6C522F70F13F73980D40238E3E21C14934D037563D930F" +
		"48198A0AA7C14058229493D22530F4DBFA336F6E0AC925139543AED44CCE7C37" +
		"20FD51F69458705AC68CD4FE6B6B13ABDC9746512969328454F18FAF8C595F64" +
		"2477FE96BB2A941D5BCD1D4AC8CC49880708FA9B378E3C4F3A9060BEE67CF9A4" +
		"A4A695811051907E162753B56B0F6B410DBA74D8A84B2A14B3144E0EF1284754" +
		"FD17ED950D5965B4B9DD46582DB1178D169C6BC465B0D6FF9CA3928FEF5B9AE4" +
		"E418FC15E83EBEA0F87FA9FF5EED70050DED2849F47BF959D956850CE929851F" +
		"0D8115F635B105EE2E4E15D04B2454BF6F4FADF034B10403119CD8E3B92FCC5B")
	// RFC 3526 group 14 and RFC 7919 ffdhe2048: safe 2048-bit primes.
	primes["modp14"] = hexInt("FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD1" +
		"29024E088A67CC74020BBEA63B139B22514A08798E3404DD" +
		"EF9519B3CD3A431B302B0A6DF25F14374FE1356D6D51C245" +
		"E485B576625E7EC6F44C42E9A637ED6B0BFF5CB6F406B7ED" +
		"EE386BFB5A899FA5AE9F24117C4B1FE649286651ECE45B3D" +
		"C2007CB8A163BF0598DA48361C55D39A69163FA8FD24CF5F" +
		"83655D23DCA3AD961C62F356208552BB9ED529077096966D" +
		"670C354E4ABC9804F1746C08CA18217C32905E462E36CE3B" +
		"E39E772C180E86039B2783A2EC07A28FB5C55DF06F4C52C9" +
		"DE2BCBF6955817183995497CEA956AE515D2261898FA0510" +
		"15728E5A8AACAA68FFFFFFFFFFFFFFFF")
	primes["ffdhe2048"] = hexInt("FFFFFFFFFFFFFFFFADF85458A2BB4A9AAFDC5620273D3CF1" +
		"D8B9C583CE2D3695A9E13641146433FBCC939DCE249B3EF9" +
		"7D2FE363630C75D8F681B202AEC4617AD3DF1ED5D5FD6561" +
		"2433F51F5F066ED0856365553DED1AF3B557135E7F57C935" +
		"984F0C70E0E68B77E2A689DAF3EFE8721DF158A136ADE735" +
		"30ACCA4F483A797ABC0AB182B324FB61D108A94BB2C8E3FB" +
		"B96ADAB760D7F4681D4F42A3DE394DF4AE56EDE76372BB19" +
		"0B07A7C8EE0A6D709E02FCE1CDF7E2ECC03404CD28342F61" +
		"9172FE9CE98583FF8E4F1232EEF28183C3FE3B1B4C6FAD73" +
		"3BB5FCBC2EC22005C58EF1837D1683B2C6F34A26C1B2EFFA" +
		"886B423861285C97FFFFFFFFFFFFFFFF")
	primes["composite"] = new(big.Int).Set(privKeys[0].N)
}

func hexInt(s string) *big.Int {
	v, ok := new(big.Int).SetString(s, 16)
	if !ok {
		panic("bad hex")
	}
	return v
}

// nextPrime returns the first probable prime at or above v (deterministic).
func nextPrime(v *big.Int) *big.Int {
	p := new(big.Int).Set(v)
	if p.Bit(0) == 0 {
		p.Add(p, big.NewInt(1))
	}
	for !p.ProbablyPrime(20) {
		p.Add(p, big.NewInt(2))
	}
	return p
}

func registerHandshake() {
	// RSA fingerprints of Telegram's keys, fixed keys, and other exponents.
	add("hs/fingerprint/telegram", func() string {
		loadData()
		var res []string
		for _, k := range tgKeys {
			res = append(res, itoa(agcrypto.RSAFingerprint(k)))
		}
		return join(res...)
	})
	for i := 0; i < 6; i++ {
		i := i
		add(fmt.Sprintf("hs/fingerprint/fixed/%d", i), func() string {
			loadData()
			pub := privKeys[i].PublicKey
			var res []string
			for _, e := range []int{65537, 3, 17, 257 + 2*i} {
				k := &rsa.PublicKey{N: pub.N, E: e}
				res = append(res, itoa(agcrypto.RSAFingerprint(k)))
			}
			return join(res...)
		})
	}

	// RSA_PAD: agent pads, reference decodes.
	for i := 0; i < 18; i++ {
		id := fmt.Sprintf("hs/rsapad/%d", i)
		i := i
		add(id, func() string {
			loadData()
			k := privKeys[i%6]
			lens := []int{144, 1, 60, 100, 143, 0, 96, 128, 32}
			data := randBytes(rng(id, "data"), lens[i%len(lens)])
			out, err := agcrypto.RSAPad(data, &k.PublicKey, rng(id, "pad"))
			if err != nil {
				return "err"
			}
			if len(out) != 256 {
				return fmt.Sprintf("len %d", len(out))
			}
			dec, err := refcrypto.DecodeRSAPad(out, k)
			if err != nil {
				return "reference decode err"
			}
			ok := len(dec) == 192 && bytes.Equal(dec[:len(data)], data)
			_, lerr := agcrypto.RSAPad(randBytes(rng(id, "long"), 145), &k.PublicKey, rng(id, "pad2"))
			return join(fmt.Sprintf("roundtrip=%v", ok), h8(data), errOr(lerr, "accepted145"))
		})
	}

	// RSA_PAD: reference pads (deterministic stream), agent decodes.
	for i := 0; i < 12; i++ {
		id := fmt.Sprintf("hs/decodersapad/%d", i)
		i := i
		add(id, func() string {
			loadData()
			k := privKeys[(i+2)%6]
			data := randBytes(rng(id, "data"), 1+i*11)
			enc, err := refcrypto.RSAPad(data, &k.PublicKey, rng(id, "pad"))
			if err != nil {
				return "reference err"
			}
			dec, err := agcrypto.DecodeRSAPad(append([]byte(nil), enc...), k)
			good := errOr(err, h8(dec))
			bad := append([]byte(nil), enc...)
			bad[100] ^= 0x10
			_, err1 := agcrypto.DecodeRSAPad(bad, k)
			_, err2 := agcrypto.DecodeRSAPad(append([]byte(nil), enc...), privKeys[(i+3)%6])
			return join(good, errOr(err1, "accepted"), errOr(err2, "accepted"))
		})
	}

	// RSA with SHA1 prefix (legacy), both directions.
	for i := 0; i < 12; i++ {
		id := fmt.Sprintf("hs/rsahashed/%d", i)
		i := i
		add(id, func() string {
			loadData()
			k := privKeys[(i+1)%6]
			lens := []int{235, 1, 40, 200, 234, 77}
			data := randBytes(rng(id, "data"), lens[i%len(lens)])
			out, err := agcrypto.RSAEncryptHashed(data, &k.PublicKey, rng(id, "pad"))
			enc := "err"
			if err == nil {
				back, err := refcrypto.RSADecryptHashed(out, k)
				enc = fmt.Sprintf("len=%d ok=%v", len(out), err == nil && bytes.Equal(back, data))
			}
			ref, err := refcrypto.RSAEncryptHashed(data, &k.PublicKey, rng(id, "refpad"))
			if err != nil {
				return "reference err"
			}
			got, err := agcrypto.RSADecryptHashed(ref, k)
			dec := errOr(err, h8(got))
			bad := append([]byte(nil), ref...)
			bad[50] ^= 0x01
			_, berr := agcrypto.RSADecryptHashed(bad, k)
			_, lerr := agcrypto.RSAEncryptHashed(randBytes(rng(id, "l"), 236), &k.PublicKey, rng(id, "p"))
			return join(enc, dec, errOr(berr, "accepted"), errOr(lerr, "accepted236"))
		})
	}

	// Raw RSA public decrypt (signature recovery).
	for i := 0; i < 8; i++ {
		id := fmt.Sprintf("hs/rsapubdec/%d", i)
		i := i
		add(id, func() string {
			loadData()
			k := privKeys[i%6]
			sig := randBytes(rng(id), 256)
			sig[0] &= 0x7f
			if i%3 == 0 {
				sig[0], sig[1] = 0, 0
			}
			m, err := agcrypto.RSAPublicDecrypt(&k.PublicKey, sig)
			good := errOr(err, hx(m))
			_, err = agcrypto.RSAPublicDecrypt(&k.PublicKey, sig[1:])
			short := "err"
			if errors.Is(err, rsa.ErrVerification) {
				short = "errverification"
			} else if err == nil {
				short = "accepted"
			}
			return join(good, short)
		})
	}

	// pq decomposition (proof of work), up to 63-bit products.
	for i := 0; i < 20; i++ {
		id := fmt.Sprintf("hs/pq/%d", i)
		i := i
		addT(id, 12*time.Second, func() string {
			var pq *big.Int
			if i == 0 {
				pq = big.NewInt(0x17ED48941A08F981)
			} else {
				r := prng(id)
				bitsP := 16 + i%16
				bitsQ := 62 - bitsP
				if bitsQ < bitsP {
					bitsQ = bitsP
				}
				p := nextPrime(new(big.Int).SetUint64(r.Uint64()>>(64-bitsP) | 1<<(bitsP-1)))
				q := nextPrime(new(big.Int).SetUint64(r.Uint64()>>(64-bitsQ) | 1<<(bitsQ-1)))
				if p.Cmp(q) == 0 {
					q = nextPrime(new(big.Int).Add(q, big.NewInt(2)))
				}
				pq = new(big.Int).Mul(p, q)
				if pq.BitLen() > 63 {
					return "skip"
				}
			}
			p, q, err := agcrypto.DecomposePQ(new(big.Int).Set(pq), rng(id, "rho"))
			if err != nil || p == nil || q == nil {
				return "err"
			}
			return fmt.Sprintf("%s,%s", p, q)
		})
	}

	// g / p quadratic residue conditions.
	for i := 0; i < 6; i++ {
		id := fmt.Sprintf("hs/checkgp/%d", i)
		i := i
		add(id, func() string {
			r := prng(id)
			base := new(big.Int).Lsh(big.NewInt(int64(r.Uint64()>>1)), 1900)
			var sb strings.Builder
			for m := 0; m < 168; m++ {
				p := new(big.Int).Add(base, big.NewInt(int64(m*5+i)))
				for g := 0; g <= 8; g++ {
					if agcrypto.CheckGP(g, p) == nil {
						sb.WriteByte('1')
					} else {
						sb.WriteByte('0')
					}
				}
			}
			return h8([]byte(sb.String())) + ":" + strings.Repeat("", 0) + countOnes(sb.String())
		})
	}

	// Full DH prime check.
	for _, name := range []string{"telegram", "modp14", "ffdhe2048", "unsafe", "unsafe1", "small", "big", "composite"} {
		name := name
		addT("hs/checkdh/"+name, 40*time.Second, func() string {
			loadData()
			p, ok := primes[name]
			if !ok {
				return "missing " + name
			}
			var res []string
			for g := 2; g <= 7; g++ {
				res = append(res, errOr(agcrypto.CheckDH(g, p), "ok"))
			}
			// Telegram's prime with g = 3 is the control that must pass.
			res = append(res, errOr(agcrypto.CheckDH(3, primes["telegram"]), "ok"))
			return join(res...)
		})
	}

	// g_a / g_b ranges.
	for i := 0; i < 8; i++ {
		id := fmt.Sprintf("hs/dhparams/%d", i)
		i := i
		add(id, func() string {
			loadData()
			p := primes[[]string{"telegram", "modp14", "ffdhe2048"}[i%3]]
			r := prng(id)
			one := big.NewInt(1)
			pm1 := new(big.Int).Sub(p, one)
			lo := new(big.Int).Lsh(one, 2048-64)
			hi := new(big.Int).Sub(p, lo)
			midSrc := rng(id, "mid")
			mid := func() *big.Int {
				v, err := crand.Int(midSrc, new(big.Int).Sub(new(big.Int).Sub(hi, lo), big.NewInt(2)))
				if err != nil {
					panic(err)
				}
				return v.Add(v, lo).Add(v, one)
			}
			g := big.NewInt(int64(2 + r.IntN(6)))
			vals := []*big.Int{
				mid(), one, big.NewInt(2), pm1, new(big.Int).Sub(pm1, one), lo, new(big.Int).Add(lo, one),
				hi, new(big.Int).Sub(hi, one), p, new(big.Int).Add(p, one), big.NewInt(0),
			}
			var sb strings.Builder
			good := mid()
			for _, v := range vals {
				sb.WriteString(errOr(agcrypto.CheckDHParams(p, g, v, good), "1"))
				sb.WriteString(errOr(agcrypto.CheckDHParams(p, g, good, v), "1"))
			}
			sb.WriteString(errOr(agcrypto.CheckDHParams(p, one, good, good), "1"))
			sb.WriteString(errOr(agcrypto.CheckDHParams(p, pm1, good, good), "1"))
			sb.WriteString(errOr(agcrypto.CheckDHParams(p, g, good, mid()), "1"))
			for _, v := range vals {
				sb.WriteString(fmt.Sprint(agcrypto.InRange(v, lo, hi)))
			}
			return h8([]byte(sb.String()))
		})
	}

	// Temporary AES keys, nonce hash, server salt.
	for i := 0; i < 16; i++ {
		id := fmt.Sprintf("hs/tempkeys/%d", i)
		i := i
		add(id, func() string {
			src := rng(id)
			nn := randBytes(src, 32)
			sn := randBytes(src, 16)
			switch i % 4 {
			case 1:
				nn[0] = 0
			case 2:
				sn[0], sn[1] = 0, 0
			case 3:
				nn[0], nn[1], nn[2] = 0, 0, 0
				sn[0] = 0
			}
			key, iv := agcrypto.TempAESKeys(new(big.Int).SetBytes(nn), new(big.Int).SetBytes(sn))
			var n256 bin.Int256
			copy(n256[:], nn)
			var n128 bin.Int128
			copy(n128[:], sn)
			var k agcrypto.Key
			copy(k[:], randBytes(src, 256))
			nh := agcrypto.NonceHash1(n256, k)
			salt := agcrypto.ServerSalt(n256, n128)
			return join(hx(key), hx(iv), hx(nh[:]), itoa(salt))
		})
	}

	// Key exchange answer encryption (data_with_hash + AES-256-IGE).
	for i := 0; i < 12; i++ {
		id := fmt.Sprintf("hs/answer/%d", i)
		i := i
		add(id, func() string {
			src := rng(id)
			key := randBytes(src, 32)
			iv := randBytes(src, 32)
			data := randBytes(src, 1+i*47)
			enc, err := agcrypto.EncryptExchangeAnswer(rng(id, "pad"), data, key, iv)
			e := "err"
			if err == nil {
				back, derr := refcrypto.DecryptExchangeAnswer(enc, key, iv)
				e = fmt.Sprintf("len16=%v ok=%v", len(enc)%16 == 0, derr == nil && bytes.Equal(back, data))
			}
			ref, err := refcrypto.EncryptExchangeAnswer(rng(id, "refpad"), data, key, iv)
			if err != nil {
				return "reference err"
			}
			got, err := agcrypto.DecryptExchangeAnswer(ref, key, iv)
			d := errOr(err, h8(got))
			_, uerr := agcrypto.DecryptExchangeAnswer(ref[:len(ref)-3], key, iv)
			return join(e, d, errOr(uerr, "accepted"))
		})
	}
}

func countOnes(s string) string {
	return itoa(strings.Count(s, "1"))
}

