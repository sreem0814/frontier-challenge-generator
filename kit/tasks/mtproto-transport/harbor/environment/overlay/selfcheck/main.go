// Command selfcheck runs sample checks of the four rebuilt packages: fixed vectors produced by a
// known-good implementation (testdata/vectors.json) and round trips of the packages against
// themselves. It prints one line per family and an estimate of the behavioural part of the score.
//
//	go run ./selfcheck            # check
//	go run ./selfcheck -v         # also list every failing vector
//
// The graded suite is larger: the same families with other inputs, every encoder checked by an
// independent decoder, both exchange roles against an independent peer and against peers that
// misbehave at each step. Passing everything here does not guarantee a full score.
package main

import (
	"bytes"
	"context"
	"crypto/rsa"
	"crypto/sha256"
	"crypto/x509"
	"encoding/hex"
	"encoding/json"
	"encoding/pem"
	"errors"
	"flag"
	"fmt"
	"io"
	"math/big"
	mrand "math/rand/v2"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/gotd/neo"

	"github.com/gotd/td/bin"
	"github.com/gotd/td/crypto"
	"github.com/gotd/td/exchange"
	"github.com/gotd/td/mtproxy"
	"github.com/gotd/td/mtproxy/obfuscated2"
	"github.com/gotd/td/proto/codec"
	"github.com/gotd/td/transport"
)

// Vector is one fixed input with the output a correct implementation produces.
type Vector struct {
	Family string            `json:"family"`
	Kind   string            `json:"kind"`
	In     map[string]string `json:"in"`
	Want   string            `json:"want"`
}

var verbose = flag.Bool("v", false, "list failing vectors")

func main() {
	gen := flag.Bool("gen", false, "regenerate testdata/vectors.json from the current packages")
	flag.Parse()
	dir := sourceDir()
	if *gen {
		vs := generate()
		b, _ := json.MarshalIndent(vs, "", " ")
		if err := os.WriteFile(filepath.Join(dir, "testdata", "vectors.json"), b, 0o644); err != nil {
			fmt.Println(err)
			os.Exit(1)
		}
		fmt.Println("wrote", len(vs), "vectors")
		return
	}
	b, err := os.ReadFile(filepath.Join(dir, "testdata", "vectors.json"))
	if err != nil {
		fmt.Println("read vectors:", err)
		os.Exit(1)
	}
	var vs []Vector
	if err := json.Unmarshal(b, &vs); err != nil {
		fmt.Println("parse vectors:", err)
		os.Exit(1)
	}
	type tally struct{ pass, total int }
	fam := map[string]*tally{}
	add := func(f string, ok bool, what string) {
		t := fam[f]
		if t == nil {
			t = &tally{}
			fam[f] = t
		}
		t.total++
		if ok {
			t.pass++
		} else if *verbose {
			fmt.Printf("  FAIL %-6s %s\n", f, what)
		}
	}
	for _, v := range vs {
		got := safe(func() string { return eval(v.Kind, v.In) })
		add(v.Family, got == v.Want, fmt.Sprintf("%s %v: got %.80q want %.80q", v.Kind, shortIn(v.In), got, v.Want))
	}
	for _, rt := range roundTrips() {
		got := safe(rt.fn)
		add(rt.family, got == "ok", rt.name+": "+got)
	}
	weights := map[string]float64{"codec": 0.06, "obfs": 0.06, "msg": 0.14, "hs": 0.12, "kex": 0.22}
	var names []string
	for k := range fam {
		names = append(names, k)
	}
	sort.Strings(names)
	est := 0.0
	for _, k := range names {
		t := fam[k]
		fmt.Printf("%-6s %4d/%-4d\n", k, t.pass, t.total)
		est += weights[k] * float64(t.pass) / float64(t.total)
	}
	fmt.Printf("estimate for these five groups: %.3f of 0.60 (sess, weight 0.32, and integration, 0.08, are not sampled here)\n", est)
}

func sourceDir() string {
	_, file, _, ok := runtime.Caller(0)
	if ok {
		if _, err := os.Stat(filepath.Join(filepath.Dir(file), "testdata")); err == nil {
			return filepath.Dir(file)
		}
	}
	return "selfcheck"
}

func shortIn(in map[string]string) string {
	var parts []string
	for k, v := range in {
		if len(v) > 16 {
			v = v[:16] + "…"
		}
		parts = append(parts, k+"="+v)
	}
	sort.Strings(parts)
	return strings.Join(parts, " ")
}

func safe(f func() string) (out string) {
	defer func() {
		if r := recover(); r != nil {
			out = fmt.Sprintf("panic: %v", r)
		}
	}()
	done := make(chan string, 1)
	go func() {
		defer func() {
			if r := recover(); r != nil {
				done <- fmt.Sprintf("panic: %v", r)
			}
		}()
		done <- f()
	}()
	select {
	case s := <-done:
		return s
	case <-time.After(30 * time.Second):
		return "timeout"
	}
}

func unhex(s string) []byte {
	b, err := hex.DecodeString(s)
	if err != nil {
		panic(err)
	}
	return b
}

func hx(b []byte) string { return hex.EncodeToString(b) }

func h8(b []byte) string {
	s := sha256.Sum256(b)
	return hex.EncodeToString(s[:8])
}

func errOr(err error, ok string) string {
	if err != nil {
		return "err"
	}
	return ok
}

func src(seed string) io.Reader {
	return mrand.NewChaCha8(sha256.Sum256([]byte("selfcheck\x00" + seed)))
}

func randBytes(r io.Reader, n int) []byte {
	b := make([]byte, n)
	if _, err := io.ReadFull(r, b); err != nil {
		panic(err)
	}
	return b
}

func codecOf(name string) codec.Codec {
	switch name {
	case "abridged":
		return codec.Abridged{}
	case "intermediate":
		return codec.Intermediate{}
	case "padded":
		return codec.PaddedIntermediate{}
	default:
		return &codec.Full{}
	}
}

func key256(s string) (k crypto.Key) {
	copy(k[:], unhex(s))
	return k
}

func i128(s string) (v bin.Int128) {
	copy(v[:], unhex(s))
	return v
}

func i256(s string) (v bin.Int256) {
	copy(v[:], unhex(s))
	return v
}

var (
	keysOnce sync.Once
	privKeys []*rsa.PrivateKey
)

// testKeys returns two fixed RSA-2048 keys (testdata/rsa*.pem).
func testKeys() []*rsa.PrivateKey {
	keysOnce.Do(func() {
		for i := 1; i <= 2; i++ {
			b, err := os.ReadFile(filepath.Join(sourceDir(), "testdata", fmt.Sprintf("rsa%d.pem", i)))
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
	})
	return privKeys
}

func dataFields(d *crypto.EncryptedMessageData) string {
	n := int(d.MessageDataLen)
	if n < 0 || n > len(d.MessageDataWithPadding) {
		return "badlen"
	}
	return fmt.Sprintf("%d/%d/%d/%d/%d/%s", d.Salt, d.SessionID, d.MessageID, d.SeqNo, d.MessageDataLen,
		h8(d.MessageDataWithPadding[:n]))
}

// eval computes the output of one vector kind with the packages under test.
func eval(kind string, in map[string]string) string {
	switch kind {
	case "codec.write":
		var w bytes.Buffer
		if err := codecOf(in["codec"]).Write(&w, &bin.Buffer{Buf: unhex(in["payload"])}); err != nil {
			return "err"
		}
		return hx(w.Bytes())
	case "codec.read":
		c := codecOf(in["codec"])
		r := bytes.NewReader(unhex(in["stream"]))
		var out []string
		for {
			if r.Len() == 0 {
				break
			}
			b := new(bin.Buffer)
			err := c.Read(r, b)
			var pe *codec.ProtocolErr
			switch {
			case errors.As(err, &pe):
				out = append(out, fmt.Sprintf("proto:%d", pe.Code))
			case err != nil:
				out = append(out, "err")
				return strings.Join(out, "|")
			default:
				out = append(out, hx(b.Buf))
			}
		}
		return strings.Join(out, "|")
	case "obfs.accept":
		rw, md, err := obfuscated2.Accept(bytes.NewBuffer(unhex(in["stream"])), unhex(in["secret"]))
		if err != nil {
			return "err"
		}
		rest, _ := io.ReadAll(rw)
		return fmt.Sprintf("%s|%d|%s", hx(md.Protocol[:]), md.DC, hx(rest))
	case "crypto.keyid":
		k := key256(in["key"])
		id, aux := k.ID(), k.AuxHash()
		return hx(id[:]) + "|" + hx(aux[:])
	case "crypto.kdf2":
		side := crypto.Side(unhex(in["side"])[0])
		k, iv := crypto.Keys(key256(in["key"]), i128(in["msgkey"]), side)
		m := crypto.MessageKey(key256(in["key"]), unhex(in["plaintext"]), side)
		return hx(k[:]) + "|" + hx(iv[:]) + "|" + hx(m[:])
	case "crypto.kdf1":
		side := crypto.Side(unhex(in["side"])[0])
		k, iv := crypto.OldKeys(key256(in["key"]), i128(in["msgkey"]), side)
		k1, iv1 := crypto.KeysV1(key256(in["key"]), i128(in["msgkey"]))
		m := crypto.MessageKeyV1(unhex(in["plaintext"]))
		return hx(k[:]) + "|" + hx(iv[:]) + "|" + hx(k1[:]) + "|" + hx(iv1[:]) + "|" + hx(m[:])
	case "crypto.decrypt":
		var c crypto.Cipher
		if in["side"] == "client" {
			c = crypto.NewClientCipher(src("x"))
		} else {
			c = crypto.NewServerCipher(src("x"))
		}
		k := key256(in["key"])
		ak := crypto.AuthKey{Value: k, ID: [8]byte(unhex(in["keyid"]))}
		d, err := c.DecryptFromBuffer(ak, &bin.Buffer{Buf: unhex(in["wire"])})
		if err != nil {
			return "err"
		}
		return dataFields(d)
	case "crypto.fingerprint":
		n, _ := new(big.Int).SetString(in["n"], 16)
		e, _ := new(big.Int).SetString(in["e"], 10)
		return fmt.Sprint(crypto.RSAFingerprint(&rsa.PublicKey{N: n, E: int(e.Int64())}))
	case "crypto.tempkeys":
		nn, sn := unhex(in["newnonce"]), unhex(in["servernonce"])
		k, iv := crypto.TempAESKeys(new(big.Int).SetBytes(nn), new(big.Int).SetBytes(sn))
		h := crypto.NonceHash1(i256(in["newnonce"]), key256(in["key"]))
		salt := crypto.ServerSalt(i256(in["newnonce"]), i128(in["servernonce"]))
		return fmt.Sprintf("%s|%s|%s|%d", hx(k), hx(iv), hx(h[:]), salt)
	case "crypto.pq":
		pq, _ := new(big.Int).SetString(in["pq"], 10)
		p, q, err := crypto.DecomposePQ(pq, src("pq"))
		if err != nil || p == nil || q == nil {
			return "err"
		}
		return p.String() + "," + q.String()
	case "crypto.checkgp":
		p, _ := new(big.Int).SetString(in["p"], 16)
		var sb strings.Builder
		for g := 0; g <= 8; g++ {
			sb.WriteString(errOr(crypto.CheckGP(g, p), "1"))
			sb.WriteByte(' ')
		}
		return sb.String()
	case "crypto.checkdh":
		p, _ := new(big.Int).SetString(in["p"], 16)
		var sb strings.Builder
		for g := 2; g <= 7; g++ {
			sb.WriteString(errOr(crypto.CheckDH(g, p), "ok"))
			sb.WriteByte(' ')
		}
		return sb.String()
	case "crypto.decodersapad":
		k := testKeys()[0]
		out, err := crypto.DecodeRSAPad(unhex(in["data"]), k)
		return errOr(err, hx(out))
	case "crypto.rsadecrypthashed":
		k := testKeys()[1]
		out, err := crypto.RSADecryptHashed(unhex(in["data"]), k)
		return errOr(err, hx(out))
	case "crypto.answer":
		out, err := crypto.DecryptExchangeAnswer(unhex(in["data"]), unhex(in["key"]), unhex(in["iv"]))
		return errOr(err, hx(out))
	case "crypto.bind":
		var m crypto.BindAuthKeyInner
		if err := m.Decode(&bin.Buffer{Buf: unhex(in["encoded"])}); err != nil {
			return "err"
		}
		b := new(bin.Buffer)
		if err := m.Encode(b); err != nil {
			return "err"
		}
		return fmt.Sprintf("%+v|%s", m, hx(b.Buf))
	}
	return "unknown kind " + kind
}

type roundTrip struct {
	family, name string
	fn           func() string
}

// msgPipe is an in-memory transport.Conn pair.
type msgPipe struct {
	in, out chan []byte
}

func (p msgPipe) Send(ctx context.Context, b *bin.Buffer) error {
	select {
	case p.out <- append([]byte(nil), b.Buf...):
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}

func (p msgPipe) Recv(ctx context.Context, b *bin.Buffer) error {
	select {
	case m := <-p.in:
		b.ResetTo(m)
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}

func (p msgPipe) Close() error { return nil }

var _ transport.Conn = msgPipe{}

func roundTrips() []roundTrip {
	var rts []roundTrip
	for _, name := range []string{"abridged", "intermediate", "padded", "full"} {
		name := name
		rts = append(rts, roundTrip{"codec", "roundtrip " + name, func() string {
			w, r := codecOf(name), codecOf(name)
			var buf bytes.Buffer
			rnd := src(name)
			var want [][]byte
			for i := 0; i < 20; i++ {
				p := randBytes(rnd, 8+4*i*37)
				want = append(want, p)
				if err := w.Write(&buf, &bin.Buffer{Buf: append([]byte(nil), p...)}); err != nil {
					return "write: " + err.Error()
				}
			}
			for i := range want {
				b := new(bin.Buffer)
				if err := r.Read(&buf, b); err != nil {
					return "read: " + err.Error()
				}
				if !bytes.Equal(b.Buf, want[i]) {
					return fmt.Sprintf("frame %d differs", i)
				}
			}
			return "ok"
		}})
	}
	for i, tag := range [][4]byte{{0xef, 0xef, 0xef, 0xef}, {0xdd, 0xdd, 0xdd, 0xdd}} {
		i, tag := i, tag
		rts = append(rts, roundTrip{"obfs", fmt.Sprintf("handshake/accept %x", tag), func() string {
			var c2s bytes.Buffer
			secret := randBytes(src("secret"), 16*i)
			cl := obfuscated2.NewObfuscated2(src(fmt.Sprint("init", i)), &c2s)
			if err := cl.Handshake(tag, 2+i, mtproxy.Secret{Secret: secret}); err != nil {
				return "handshake: " + err.Error()
			}
			msg := randBytes(src("msg"), 1000)
			if _, err := cl.Write(msg); err != nil {
				return "write: " + err.Error()
			}
			rw, md, err := obfuscated2.Accept(&c2s, secret)
			if err != nil {
				return "accept: " + err.Error()
			}
			got := make([]byte, len(msg))
			if _, err := io.ReadFull(rw, got); err != nil {
				return "read: " + err.Error()
			}
			if md.Protocol != tag || int(md.DC) != 2+i || !bytes.Equal(got, msg) {
				return "mismatch"
			}
			return "ok"
		}})
	}
	for i := 0; i < 2; i++ {
		i := i
		rts = append(rts, roundTrip{"msg", fmt.Sprintf("encrypt/decrypt %d", i), func() string {
			var k crypto.Key
			copy(k[:], randBytes(src("key"), 256))
			ak := k.WithID()
			enc, dec := crypto.NewClientCipher(src("pad")), crypto.NewServerCipher(src("pad2"))
			if i == 1 {
				enc, dec = dec, enc
			}
			body := randBytes(src("body"), 400)
			d := crypto.EncryptedMessageData{Salt: 1, SessionID: 2, MessageID: 3, SeqNo: 4,
				MessageDataLen: int32(len(body)), MessageDataWithPadding: body}
			b := new(bin.Buffer)
			if err := enc.Encrypt(ak, d, b); err != nil {
				return "encrypt: " + err.Error()
			}
			got, err := dec.DecryptFromBuffer(ak, b)
			if err != nil {
				return "decrypt: " + err.Error()
			}
			if !bytes.Equal(got.Data(), body) || got.MessageID != 3 {
				return "mismatch"
			}
			return "ok"
		}})
	}
	rts = append(rts, roundTrip{"hs", "rsa_pad", func() string {
		k := testKeys()[0]
		data := randBytes(src("rsapad"), 144)
		enc, err := crypto.RSAPad(data, &k.PublicKey, src("p"))
		if err != nil {
			return "pad: " + err.Error()
		}
		dec, err := crypto.DecodeRSAPad(enc, k)
		if err != nil {
			return "decode: " + err.Error()
		}
		if len(enc) != 256 || len(dec) != 192 || !bytes.Equal(dec[:144], data) {
			return "mismatch"
		}
		return "ok"
	}})
	rts = append(rts, roundTrip{"hs", "exchange answer", func() string {
		key, iv := randBytes(src("k"), 32), randBytes(src("iv"), 32)
		data := randBytes(src("d"), 333)
		enc, err := crypto.EncryptExchangeAnswer(src("pad"), data, key, iv)
		if err != nil {
			return "encrypt: " + err.Error()
		}
		dec, err := crypto.DecryptExchangeAnswer(enc, key, iv)
		if err != nil || !bytes.Equal(dec, data) {
			return "mismatch"
		}
		return "ok"
	}})
	for _, temp := range []bool{false, true} {
		temp := temp
		rts = append(rts, roundTrip{"kex", fmt.Sprintf("client/server temp=%v", temp), func() string {
			k := testKeys()[1]
			c1, c2 := make(chan []byte, 8), make(chan []byte, 8)
			now := neo.NewTime(time.Unix(1767225600, 0))
			ex := exchange.NewExchanger(msgPipe{in: c1, out: c2}, 2).WithRand(src("c")).WithClock(now)
			if temp {
				ex = ex.WithTempMode(3600)
			}
			cl := ex.Client([]exchange.PublicKey{{RSA: &testKeys()[0].PublicKey}, {RSA: &k.PublicKey}})
			srv := exchange.NewExchanger(msgPipe{in: c2, out: c1}, 2).WithRand(src("s")).WithClock(now).
				Server(exchange.PrivateKey{RSA: k})
			ctx, cancel := context.WithTimeout(context.Background(), 25*time.Second)
			defer cancel()
			var sr exchange.ServerExchangeResult
			var serr error
			done := make(chan struct{})
			go func() {
				defer close(done)
				sr, serr = srv.Run(ctx)
			}()
			cr, cerr := cl.Run(ctx)
			cancel()
			<-done
			switch {
			case cerr != nil:
				return "client: " + cerr.Error()
			case serr != nil:
				return "server: " + serr.Error()
			case cr.AuthKey.Value != sr.Key.Value || cr.AuthKey.ID != sr.Key.Value.ID():
				return "keys differ"
			case cr.ServerSalt != sr.ServerSalt:
				return "salt differs"
			case temp && cr.ExpiresAt != now.Now().Unix()+3600:
				return "expires_at"
			}
			return "ok"
		}})
	}
	return rts
}

// generate builds the vectors with the current packages (used once, against a known-good tree).
func generate() []Vector {
	var vs []Vector
	addv := func(family, kind string, in map[string]string) {
		vs = append(vs, Vector{Family: family, Kind: kind, In: in, Want: eval(kind, in)})
	}
	r := src("gen")
	for _, c := range []string{"abridged", "intermediate", "full"} {
		for _, n := range []int{8, 100, 508, 512, 2000} {
			addv("codec", "codec.write", map[string]string{"codec": c, "payload": hx(randBytes(r, n))})
		}
	}
	for _, c := range []string{"abridged", "intermediate", "padded", "full"} {
		for j := 0; j < 3; j++ {
			var stream bytes.Buffer
			w := codecOf(c)
			for i := 0; i < 3+j; i++ {
				_ = w.Write(&stream, &bin.Buffer{Buf: randBytes(r, 4*(2+i*61+j))})
			}
			if j == 1 {
				_ = w.Write(&stream, &bin.Buffer{Buf: []byte{0x6c, 0xfe, 0xff, 0xff}}) // -404
			}
			addv("codec", "codec.read", map[string]string{"codec": c, "stream": hx(stream.Bytes())})
		}
	}
	for i := 0; i < 6; i++ {
		var buf bytes.Buffer
		secret := randBytes(r, 16*(i%2))
		cl := obfuscated2.NewObfuscated2(r, &buf)
		tags := [][4]byte{{0xef, 0xef, 0xef, 0xef}, {0xee, 0xee, 0xee, 0xee}, {0xdd, 0xdd, 0xdd, 0xdd}}
		_ = cl.Handshake(tags[i%3], []int{1, 2, -2, 4, 5, 203}[i], mtproxy.Secret{Secret: secret})
		_, _ = cl.Write(randBytes(r, 100+i*50))
		addv("obfs", "obfs.accept", map[string]string{"stream": hx(buf.Bytes()), "secret": hx(secret)})
	}
	for i := 0; i < 4; i++ {
		addv("msg", "crypto.keyid", map[string]string{"key": hx(randBytes(r, 256))})
		addv("msg", "crypto.kdf2", map[string]string{"key": hx(randBytes(r, 256)), "msgkey": hx(randBytes(r, 16)),
			"side": fmt.Sprintf("%02x", i%2), "plaintext": hx(randBytes(r, 64+16*i))})
		addv("msg", "crypto.kdf1", map[string]string{"key": hx(randBytes(r, 256)), "msgkey": hx(randBytes(r, 16)),
			"side": fmt.Sprintf("%02x", i%2), "plaintext": hx(randBytes(r, 40+i))})
	}
	for i := 0; i < 6; i++ {
		var k crypto.Key
		copy(k[:], randBytes(r, 256))
		ak := k.WithID()
		enc := crypto.NewClientCipher(r)
		side := "server"
		if i%2 == 1 {
			enc, side = crypto.NewServerCipher(r), "client"
		}
		body := randBytes(r, 4*(3+i*29))
		b := new(bin.Buffer)
		_ = enc.Encrypt(ak, crypto.EncryptedMessageData{Salt: int64(i) * 7, SessionID: -5, MessageID: 1 << 40,
			SeqNo: int32(i), MessageDataLen: int32(len(body)), MessageDataWithPadding: body}, b)
		if i == 5 {
			b.Buf[40] ^= 1 // tampered: must be rejected
		}
		addv("msg", "crypto.decrypt", map[string]string{"side": side, "key": hx(k[:]), "keyid": hx(ak.ID[:]),
			"wire": hx(b.Buf)})
	}
	for i := 0; i < 2; i++ {
		b := new(bin.Buffer)
		_ = (&crypto.BindAuthKeyInner{Nonce: int64(i) + 1, TempAuthKeyID: -2, PermAuthKeyID: 3, TempSessionID: 4,
			ExpiresAt: 1767225600}).Encode(b)
		addv("msg", "crypto.bind", map[string]string{"encoded": hx(b.Buf)})
	}
	for i, k := range testKeys() {
		addv("hs", "crypto.fingerprint", map[string]string{"n": k.N.Text(16), "e": fmt.Sprint(k.E)})
		addv("hs", "crypto.fingerprint", map[string]string{"n": k.N.Text(16), "e": fmt.Sprint(3 + 2*i)})
	}
	for i := 0; i < 4; i++ {
		nn, sn := randBytes(r, 32), randBytes(r, 16)
		if i == 1 {
			nn[0] = 0
		}
		if i == 2 {
			sn[0] = 0
		}
		addv("hs", "crypto.tempkeys", map[string]string{"newnonce": hx(nn), "servernonce": hx(sn),
			"key": hx(randBytes(r, 256))})
	}
	for _, pq := range []string{"1724114033281923457", "2474517835788694711", "2734866425258632087", "4336158129900539441"} {
		addv("hs", "crypto.pq", map[string]string{"pq": pq})
	}
	tg := "C71CAEB9C6B1C9048E6C522F70F13F73980D40238E3E21C14934D037563D930F48198A0AA7C14058229493D22530F4DBFA336F6E0AC925139543AED44CCE7C3720FD51F69458705AC68CD4FE6B6B13ABDC9746512969328454F18FAF8C595F642477FE96BB2A941D5BCD1D4AC8CC49880708FA9B378E3C4F3A9060BEE67CF9A4A4A695811051907E162753B56B0F6B410DBA74D8A84B2A14B3144E0EF1284754FD17ED950D5965B4B9DD46582DB1178D169C6BC465B0D6FF9CA3928FEF5B9AE4E418FC15E83EBEA0F87FA9FF5EED70050DED2849F47BF959D956850CE929851F0D8115F635B105EE2E4E15D04B2454BF6F4FADF034B10403119CD8E3B92FCC5B"
	addv("hs", "crypto.checkdh", map[string]string{"p": tg})
	addv("hs", "crypto.checkdh", map[string]string{"p": testKeys()[0].N.Text(16)})
	for i := 0; i < 3; i++ {
		addv("hs", "crypto.checkgp", map[string]string{"p": hx(randBytes(r, 256))})
	}
	for i := 0; i < 2; i++ {
		enc, _ := crypto.RSAPad(randBytes(r, 50+i*90), &testKeys()[0].PublicKey, r)
		addv("hs", "crypto.decodersapad", map[string]string{"data": hx(enc)})
		h, _ := crypto.RSAEncryptHashed(randBytes(r, 60+i*100), &testKeys()[1].PublicKey, r)
		addv("hs", "crypto.rsadecrypthashed", map[string]string{"data": hx(h)})
		key, iv := randBytes(r, 32), randBytes(r, 32)
		a, _ := crypto.EncryptExchangeAnswer(r, randBytes(r, 100+i*7), key, iv)
		addv("hs", "crypto.answer", map[string]string{"data": hx(a), "key": hx(key), "iv": hx(iv)})
	}
	return vs
}
