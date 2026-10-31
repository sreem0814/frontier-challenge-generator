package main

import (
	"context"
	crand "crypto/rand"
	"crypto/rsa"
	"errors"
	"fmt"
	"io"
	"math/big"
	"strings"
	"sync"
	"time"

	"github.com/gotd/neo"

	"github.com/gotd/td/bin"
	agex "github.com/gotd/td/exchange"
	refcrypto "github.com/gotd/td/internal/zref/crypto"
	refex "github.com/gotd/td/internal/zref/exchange"
	"github.com/gotd/td/mt"
	agcodec "github.com/gotd/td/proto/codec"
	"github.com/gotd/td/proto"
)

var kexNow = time.Unix(1767225600, 0)

// msgConn is one end of an in-memory message pipe implementing
// transport.Conn. inject holds errors returned by the first Recv calls.
type msgConn struct {
	in     chan pipeItem
	out    chan pipeItem
	closed chan struct{}
	once   *sync.Once
	mu     sync.Mutex
	inject []error
	sent   []uint32
}

// pipeItem is a message or a transport error delivered to the peer's Recv.
type pipeItem struct {
	b   []byte
	err error
}

func msgPipe() (a, b *msgConn) {
	c1, c2 := make(chan pipeItem, 64), make(chan pipeItem, 64)
	closed := make(chan struct{})
	once := new(sync.Once)
	return &msgConn{in: c1, out: c2, closed: closed, once: once},
		&msgConn{in: c2, out: c1, closed: closed, once: once}
}

func (c *msgConn) Send(ctx context.Context, b *bin.Buffer) error {
	msg := append([]byte(nil), b.Buf...)
	c.mu.Lock()
	c.sent = append(c.sent, typeOf(msg))
	c.mu.Unlock()
	select {
	case <-c.closed:
		return io.ErrClosedPipe
	default:
	}
	select {
	case c.out <- pipeItem{b: msg}:
		return nil
	case <-c.closed:
		return io.ErrClosedPipe
	case <-ctx.Done():
		return ctx.Err()
	}
}

func (c *msgConn) Recv(ctx context.Context, b *bin.Buffer) error {
	c.mu.Lock()
	if len(c.inject) > 0 {
		err := c.inject[0]
		c.inject = c.inject[1:]
		c.mu.Unlock()
		return err
	}
	c.mu.Unlock()
	// Messages already queued are delivered even after the pipe is closed.
	deliver := func(m pipeItem) error {
		if m.err != nil {
			return m.err
		}
		b.ResetTo(append([]byte(nil), m.b...))
		return nil
	}
	select {
	case m := <-c.in:
		return deliver(m)
	default:
	}
	select {
	case m := <-c.in:
		return deliver(m)
	case <-c.closed:
		select {
		case m := <-c.in:
			return deliver(m)
		default:
			return io.EOF
		}
	case <-ctx.Done():
		return ctx.Err()
	}
}

// sendErr delivers a transport error to the peer's next Recv.
func (c *msgConn) sendErr(err error) {
	select {
	case c.out <- pipeItem{err: err}:
	case <-c.closed:
	}
}

func (c *msgConn) Close() error {
	c.once.Do(func() { close(c.closed) })
	return nil
}

func (c *msgConn) sentNames() string {
	c.mu.Lock()
	defer c.mu.Unlock()
	var names []string
	for _, id := range c.sent {
		names = append(names, tlName(id))
	}
	if len(names) == 0 {
		return "none"
	}
	return strings.Join(names, ",")
}

// typeOf returns the TL type id inside a plaintext message (0 if not one).
func typeOf(msg []byte) uint32 {
	var m proto.UnencryptedMessage
	if err := m.Decode(&bin.Buffer{Buf: msg}); err != nil || len(m.MessageData) < 4 {
		return 0
	}
	id, _ := (&bin.Buffer{Buf: m.MessageData}).PeekID()
	return id
}

func tlName(id uint32) string {
	switch id {
	case mt.ReqPqRequestTypeID:
		return "req_pq"
	case mt.ReqPqMultiRequestTypeID:
		return "req_pq_multi"
	case mt.ReqDHParamsRequestTypeID:
		return "req_DH_params"
	case mt.SetClientDHParamsRequestTypeID:
		return "set_client_DH_params"
	case 0:
		return "garbage"
	default:
		return fmt.Sprintf("%08x", id)
	}
}

func writePlain(ctx context.Context, c *msgConn, typ proto.MessageType, data bin.Encoder) error {
	b := new(bin.Buffer)
	if err := data.Encode(b); err != nil {
		return err
	}
	msg := proto.UnencryptedMessage{MessageID: int64(proto.NewMessageID(kexNow, typ)), MessageData: b.Copy()}
	out := new(bin.Buffer)
	if err := msg.Encode(out); err != nil {
		return err
	}
	return c.Send(ctx, out)
}

func readPlain(ctx context.Context, c *msgConn) (*bin.Buffer, error) {
	b := new(bin.Buffer)
	if err := c.Recv(ctx, b); err != nil {
		return nil, err
	}
	var msg proto.UnencryptedMessage
	if err := msg.Decode(b); err != nil {
		return nil, err
	}
	return &bin.Buffer{Buf: msg.MessageData}, nil
}

func testClock() *neo.Time { return neo.NewTime(kexNow) }

type kexResult struct {
	err error
	val any
}

// both runs two functions concurrently and closes the pipe when both end
// or after the deadline.
func both(timeout time.Duration, conn *msgConn, a, b func(ctx context.Context) kexResult) (kexResult, kexResult) {
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	ra, rb := make(chan kexResult, 1), make(chan kexResult, 1)
	run := func(f func(ctx context.Context) kexResult, out chan kexResult) {
		defer func() {
			if r := recover(); r != nil {
				out <- kexResult{err: fmt.Errorf("panic: %v", r)}
			}
		}()
		out <- f(ctx)
	}
	go run(a, ra)
	go run(b, rb)
	var x, y kexResult
	gotA, gotB := false, false
	for !(gotA && gotB) {
		select {
		case x = <-ra:
			gotA = true
			_ = conn.Close()
		case y = <-rb:
			gotB = true
			_ = conn.Close()
		case <-ctx.Done():
			_ = conn.Close()
			if !gotA {
				x = kexResult{err: errors.New("timeout")}
			}
			if !gotB {
				y = kexResult{err: errors.New("timeout")}
			}
			return x, y
		}
	}
	return x, y
}

func keyID(k [256]byte) [8]byte { return refcrypto.Key(k).ID() }

func registerKex() {
	// Agent client against reference server.
	for i := 0; i < 14; i++ {
		id := fmt.Sprintf("kex/client/%d", i)
		i := i
		addT(id, 60*time.Second, func() string {
			loadData()
			dc := []int{2, 1, 3, 4, 5, -2, 203}[i%7]
			srvKey := privKeys[i%6]
			a, b := msgPipe()
			ex := agex.NewExchanger(a, dc).WithRand(rng(id, "client")).WithClock(testClock()).WithTimeout(20 * time.Second)
			temp := i%3 == 2
			expires := 0
			if temp {
				expires = 3600 * (1 + i)
				ex = ex.WithTempMode(expires)
			}
			var keys []agex.PublicKey
			for j := 0; j < 1+i%4; j++ {
				keys = append(keys, agex.PublicKey{RSA: &privKeys[(i+1+j)%6].PublicKey})
			}
			keys = append(keys, agex.PublicKey{RSA: &srvKey.PublicKey})
			if i%5 == 4 {
				keys = []agex.PublicKey{keys[len(keys)-1], {RSA: &privKeys[(i+2)%6].PublicKey}}
			}
			srv := refex.NewExchanger(b, dc).WithRand(rng(id, "server")).WithClock(testClock()).WithTimeout(20 * time.Second).
				Server(refex.PrivateKey{RSA: srvKey})
			cl := ex.Client(keys)
			cr, sr := both(50*time.Second, a,
				func(ctx context.Context) kexResult { r, err := cl.Run(ctx); return kexResult{err, r} },
				func(ctx context.Context) kexResult { r, err := srv.Run(ctx); return kexResult{err, r} })
			if cr.err != nil {
				return "client err; sent=" + a.sentNames()
			}
			if sr.err != nil {
				return "server err; sent=" + a.sentNames()
			}
			c := cr.val.(agex.ClientExchangeResult)
			s := sr.val.(refex.ServerExchangeResult)
			return join(
				fmt.Sprintf("keyeq=%v", c.AuthKey.Value == agKeyCast(s.Key.Value)),
				fmt.Sprintf("id=%v", c.AuthKey.ID == keyID(c.AuthKey.Value)),
				fmt.Sprintf("salt=%v", c.ServerSalt == s.ServerSalt),
				fmt.Sprintf("session=%v", c.SessionID != 0),
				fmt.Sprintf("expires=%d", c.ExpiresAt-kexNow.Unix()*boolInt(c.ExpiresAt != 0)),
				"sent="+a.sentNames(),
			)
		})
	}

	// Reference client against agent server.
	for i := 0; i < 10; i++ {
		id := fmt.Sprintf("kex/server/%d", i)
		i := i
		addT(id, 60*time.Second, func() string {
			loadData()
			dc := []int{2, 4, 1, -3, 5}[i%5]
			srvKey := privKeys[(i+3)%6]
			a, b := msgPipe()
			ex := refex.NewExchanger(a, dc).WithRand(rng(id, "client")).WithClock(testClock()).WithTimeout(20 * time.Second)
			if i%2 == 1 {
				ex = ex.WithTempMode(86400)
			}
			keys := []refex.PublicKey{{RSA: &privKeys[(i+4)%6].PublicKey}, {RSA: &srvKey.PublicKey}}
			cl := ex.Client(keys)
			srv := agex.NewExchanger(b, dc).WithRand(rng(id, "server")).WithClock(testClock()).WithTimeout(20 * time.Second).
				Server(agex.PrivateKey{RSA: srvKey})
			cr, sr := both(50*time.Second, a,
				func(ctx context.Context) kexResult { r, err := cl.Run(ctx); return kexResult{err, r} },
				func(ctx context.Context) kexResult { r, err := srv.Run(ctx); return kexResult{err, r} })
			if sr.err != nil {
				return "server err; sent=" + a.sentNames()
			}
			if cr.err != nil {
				return "reference client err; sent=" + a.sentNames()
			}
			c := cr.val.(refex.ClientExchangeResult)
			s := sr.val.(agex.ServerExchangeResult)
			return join(
				fmt.Sprintf("keyeq=%v", c.AuthKey.Value == refKeyCast(s.Key.Value)),
				fmt.Sprintf("id=%v", s.Key.ID == keyID(s.Key.Value)),
				fmt.Sprintf("salt=%v", c.ServerSalt == s.ServerSalt),
			)
		})
	}

	// Client against a scripted server that misbehaves at one step.
	for _, f := range []srvFault{
		fNone, fInject404, fNonceResPQ, fNoFingerprint, fBigPQ, fParamsFail, fOkNonce, fOkServerNonce,
		fBadPrime, fUnsafePrime, fBadG, fGAOne, fGASmall, fInnerNonce, fInnerServerNonce, fBadAnswer,
		fBadHash, fGenRetry, fGenFail, fGenOkNonce, fFingerprintSecond, fTempMode,
	} {
		f := f
		id := "kex/clientfault/" + f.String()
		addT(id, 60*time.Second, func() string {
			loadData()
			a, b := msgPipe()
			srvKey := privKeys[1]
			if f == fInject404 {
				a.inject = []error{&agcodec.ProtocolErr{Code: 404}, &agcodec.ProtocolErr{Code: 404}}
			}
			ex := agex.NewExchanger(a, 2).WithRand(rng(id, "client")).WithClock(testClock()).WithTimeout(20 * time.Second)
			if f == fTempMode {
				ex = ex.WithTempMode(7200)
			}
			keys := []agex.PublicKey{{RSA: &srvKey.PublicKey}}
			if f == fFingerprintSecond {
				keys = []agex.PublicKey{{RSA: &privKeys[4].PublicKey}, {RSA: &srvKey.PublicKey}}
			}
			cl := ex.Client(keys)
			cr, sr := both(50*time.Second, a,
				func(ctx context.Context) kexResult { r, err := cl.Run(ctx); return kexResult{err, r} },
				func(ctx context.Context) kexResult { return scriptedServer(ctx, b, srvKey, f, rng(id, "server")) })
			res := "ok"
			if cr.err != nil {
				res = "err"
				if errors.Is(cr.err, agex.ErrKeyFingerprintNotFound) {
					res = "nofingerprint"
				}
			} else if sr.err == nil {
				c := cr.val.(agex.ClientExchangeResult)
				s := sr.val.(scriptedResult)
				res = fmt.Sprintf("ok keyeq=%v salt=%v temp=%v", c.AuthKey.Value == s.key && c.AuthKey.ID == keyID(s.key),
					c.ServerSalt == s.salt, s.temp)
			} else {
				res = "ok; server: " + sr.err.Error()
			}
			return join(res, "sent="+a.sentNames())
		})
	}

	// Server against a scripted client that misbehaves at one step.
	for _, f := range []cliFault{
		cNone, cLegacy, cRepeat, cTemp, cWrongDC, cWrongDCTemp, cWrongRSA, cGarbageDH, cUnalignedDH,
		cEncryptedFirst, cEncryptedSecond, cNegativeDC,
	} {
		f := f
		id := "kex/serverfault/" + f.String()
		addT(id, 60*time.Second, func() string {
			loadData()
			dc := 2
			if f == cNegativeDC {
				dc = -2
			}
			a, b := msgPipe()
			srvKey := privKeys[2]
			srv := agex.NewExchanger(b, dc).WithRand(rng(id, "server")).WithClock(testClock()).WithTimeout(20 * time.Second).
				Server(agex.PrivateKey{RSA: srvKey})
			cr, sr := both(50*time.Second, a,
				func(ctx context.Context) kexResult { return scriptedClient(ctx, a, srvKey, dc, f, rng(id, "client")) },
				func(ctx context.Context) kexResult { r, err := srv.Run(ctx); return kexResult{err, r} })
			var server string
			if sr.err != nil {
				var se *agex.ServerExchangeError
				var ue *agex.UnexpectedEncryptedError
				switch {
				case errors.As(sr.err, &se):
					server = fmt.Sprintf("code=%d", se.Code)
				case errors.As(sr.err, &ue):
					server = fmt.Sprintf("encrypted=%s:%s", hx(ue.AuthKeyID[:]), h8(ue.Frame))
				default:
					server = "err"
				}
			} else {
				s := sr.val.(agex.ServerExchangeResult)
				if cr.err != nil {
					server = "ok; client: " + cr.err.Error()
				} else {
					c := cr.val.(scriptedResult)
					server = fmt.Sprintf("ok keyeq=%v id=%v salt=%v", s.Key.Value == agKeyCast(c.key),
						s.Key.ID == keyID(s.Key.Value), s.ServerSalt == c.salt)
				}
			}
			return server
		})
	}
}

func boolInt(b bool) int64 {
	if b {
		return 1
	}
	return 0
}

func agKeyCast(k refcrypto.Key) [256]byte { return k }
func refKeyCast(k [256]byte) refcrypto.Key { return k }

type scriptedResult struct {
	key  [256]byte
	salt int64
	temp bool
}

type srvFault int

const (
	fNone srvFault = iota
	fInject404
	fNonceResPQ
	fNoFingerprint
	fBigPQ
	fParamsFail
	fOkNonce
	fOkServerNonce
	fBadPrime
	fUnsafePrime
	fBadG
	fGAOne
	fGASmall
	fInnerNonce
	fInnerServerNonce
	fBadAnswer
	fBadHash
	fGenRetry
	fGenFail
	fGenOkNonce
	fFingerprintSecond
	fTempMode
)

func (f srvFault) String() string {
	return [...]string{"none", "inject404", "respq-nonce", "no-fingerprint", "big-pq", "params-fail", "ok-nonce",
		"ok-server-nonce", "composite-prime", "unsafe-prime", "bad-g", "ga-one", "ga-small", "inner-nonce",
		"inner-server-nonce", "bad-answer", "bad-hash", "gen-retry", "gen-fail", "genok-nonce",
		"fingerprint-second", "temp-mode"}[f]
}

func flip(v bin.Int128) bin.Int128 {
	v[5] ^= 0x40
	return v
}

// scriptedServer plays the server side of the key exchange with reference
// primitives and injects fault f.
func scriptedServer(ctx context.Context, c *msgConn, key *rsa.PrivateKey, f srvFault, src io.Reader) kexResult {
	const typ = proto.MessageServerResponse
	b, err := readPlain(ctx, c)
	if err != nil {
		return kexResult{err: err}
	}
	var req mt.ReqPqMultiRequest
	if err := req.Decode(b); err != nil {
		return kexResult{err: err}
	}
	serverNonce := i128(src)
	pq := big.NewInt(0x17ED48941A08F981)
	if f == fBigPQ {
		pq = new(big.Int).Mul(big.NewInt(3037000507), big.NewInt(3037000537)) // just above 2^63
	}
	fp := refcrypto.RSAFingerprint(&key.PublicKey)
	fps := []int64{fp}
	switch f {
	case fNoFingerprint:
		fps = []int64{fp ^ 0x55, 12345}
	case fFingerprintSecond:
		fps = []int64{777, fp}
	}
	nonce := req.Nonce
	if f == fNonceResPQ {
		nonce = flip(nonce)
	}
	if err := writePlain(ctx, c, typ, &mt.ResPQ{Nonce: nonce, ServerNonce: serverNonce, Pq: pq.Bytes(),
		ServerPublicKeyFingerprints: fps}); err != nil {
		return kexResult{err: err}
	}

	b, err = readPlain(ctx, c)
	if err != nil {
		return kexResult{err: err}
	}
	var dhReq mt.ReqDHParamsRequest
	if err := dhReq.Decode(b); err != nil {
		return kexResult{err: err}
	}
	raw, err := refcrypto.DecodeRSAPad(dhReq.EncryptedData, key)
	if err != nil {
		return kexResult{err: fmt.Errorf("rsa pad: %w", err)}
	}
	inner, err := mt.DecodePQInnerData(&bin.Buffer{Buf: raw})
	if err != nil {
		return kexResult{err: fmt.Errorf("inner: %w", err)}
	}
	newNonce := inner.GetNewNonce()
	_, temp := inner.(*mt.PQInnerDataTempDC)
	if inner.GetNonce() != req.Nonce || inner.GetServerNonce() != serverNonce {
		return kexResult{err: errors.New("client inner nonce mismatch")}
	}

	if f == fParamsFail {
		if err := writePlain(ctx, c, typ, &mt.ServerDHParamsFail{Nonce: req.Nonce, ServerNonce: serverNonce}); err != nil {
			return kexResult{err: err}
		}
		return kexResult{err: errors.New("sent fail")}
	}

	g := 3
	dhPrime := primes["telegram"]
	switch f {
	case fBadPrime:
		dhPrime = primes["composite"]
	case fUnsafePrime:
		dhPrime = primes["unsafe"]
		g = 4
	case fBadG:
		g = 2 // the Telegram prime is not 7 mod 8
	}
	one := big.NewInt(1)
	a, err := crand.Int(src, new(big.Int).Lsh(one, 2048))
	if err != nil {
		return kexResult{err: err}
	}
	ga := new(big.Int).Exp(big.NewInt(int64(g)), a, dhPrime)
	switch f {
	case fGAOne:
		ga = big.NewInt(1)
	case fGASmall:
		ga = new(big.Int).Lsh(one, 1900)
	}
	sdh := mt.ServerDHInnerData{Nonce: req.Nonce, ServerNonce: serverNonce, G: g, DhPrime: dhPrime.Bytes(),
		GA: ga.Bytes(), ServerTime: int(kexNow.Unix())}
	switch f {
	case fInnerNonce:
		sdh.Nonce = flip(sdh.Nonce)
	case fInnerServerNonce:
		sdh.ServerNonce = flip(sdh.ServerNonce)
	}
	ib := new(bin.Buffer)
	if err := sdh.Encode(ib); err != nil {
		return kexResult{err: err}
	}
	tk, tiv := refcrypto.TempAESKeys(newNonce.BigInt(), serverNonce.BigInt())
	answer, err := refcrypto.EncryptExchangeAnswer(src, ib.Buf, tk, tiv)
	if err != nil {
		return kexResult{err: err}
	}
	if f == fBadAnswer {
		answer[len(answer)/2] ^= 0x20
	}
	ok := &mt.ServerDHParamsOk{Nonce: req.Nonce, ServerNonce: serverNonce, EncryptedAnswer: answer}
	switch f {
	case fOkNonce:
		ok.Nonce = flip(ok.Nonce)
	case fOkServerNonce:
		ok.ServerNonce = flip(ok.ServerNonce)
	}
	if err := writePlain(ctx, c, typ, ok); err != nil {
		return kexResult{err: err}
	}

	b, err = readPlain(ctx, c)
	if err != nil {
		return kexResult{err: err}
	}
	var setReq mt.SetClientDHParamsRequest
	if err := setReq.Decode(b); err != nil {
		return kexResult{err: err}
	}
	dec, err := refcrypto.DecryptExchangeAnswer(setReq.EncryptedData, tk, tiv)
	if err != nil || dec == nil {
		return kexResult{err: errors.New("client DH inner data")}
	}
	var cdh mt.ClientDHInnerData
	if err := cdh.Decode(&bin.Buffer{Buf: dec}); err != nil {
		return kexResult{err: err}
	}
	if cdh.Nonce != req.Nonce || cdh.ServerNonce != serverNonce || cdh.RetryID != 0 {
		return kexResult{err: errors.New("client DH inner data fields")}
	}
	gb := new(big.Int).SetBytes(cdh.GB)
	if err := refcrypto.CheckDHParams(dhPrime, big.NewInt(int64(g)), ga, gb); err != nil {
		return kexResult{err: fmt.Errorf("g_b: %w", err)}
	}
	var authKey refcrypto.Key
	if !refcrypto.FillBytes(new(big.Int).Exp(gb, a, dhPrime), authKey[:]) {
		return kexResult{err: errors.New("auth key size")}
	}
	hash := refcrypto.NonceHash1(newNonce, authKey)
	var answerMsg bin.Encoder = &mt.DhGenOk{Nonce: req.Nonce, ServerNonce: serverNonce, NewNonceHash1: hash}
	switch f {
	case fBadHash:
		answerMsg = &mt.DhGenOk{Nonce: req.Nonce, ServerNonce: serverNonce, NewNonceHash1: flip(hash)}
	case fGenOkNonce:
		answerMsg = &mt.DhGenOk{Nonce: flip(req.Nonce), ServerNonce: serverNonce, NewNonceHash1: hash}
	case fGenRetry:
		answerMsg = &mt.DhGenRetry{Nonce: req.Nonce, ServerNonce: serverNonce, NewNonceHash2: hash}
	case fGenFail:
		answerMsg = &mt.DhGenFail{Nonce: req.Nonce, ServerNonce: serverNonce, NewNonceHash3: hash}
	}
	if err := writePlain(ctx, c, typ, answerMsg); err != nil {
		return kexResult{err: err}
	}
	return kexResult{val: scriptedResult{key: authKey, salt: refcrypto.ServerSalt(newNonce, serverNonce), temp: temp}}
}

type cliFault int

const (
	cNone cliFault = iota
	cLegacy
	cRepeat
	cTemp
	cWrongDC
	cWrongDCTemp
	cWrongRSA
	cGarbageDH
	cUnalignedDH
	cEncryptedFirst
	cEncryptedSecond
	cNegativeDC
)

func (f cliFault) String() string {
	return [...]string{"none", "legacy-req-pq", "repeat-req-pq", "temp", "wrong-dc", "wrong-dc-temp", "wrong-rsa",
		"garbage-client-dh", "unaligned-client-dh", "encrypted-first", "encrypted-second", "negative-dc"}[f]
}

func encryptedFrame(src io.Reader) []byte {
	k := randKey(src)
	id := refcrypto.Key(k).ID()
	out := append([]byte(nil), id[:]...)
	return append(out, randBytes(src, 16+64)...)
}

// scriptedClient plays the client side with reference primitives and
// injects fault f.
func scriptedClient(ctx context.Context, c *msgConn, key *rsa.PrivateKey, dc int, f cliFault, src io.Reader) kexResult {
	const typ = proto.MessageFromClient
	if f == cEncryptedFirst {
		if err := c.Send(ctx, &bin.Buffer{Buf: encryptedFrame(src)}); err != nil {
			return kexResult{err: err}
		}
		select {
		case <-ctx.Done():
		case <-c.closed:
		}
		return kexResult{err: errors.New("done")}
	}
	nonce := i128(src)
	var first bin.Encoder = &mt.ReqPqMultiRequest{Nonce: nonce}
	if f == cLegacy {
		first = &mt.ReqPqRequest{Nonce: nonce}
	}
	if err := writePlain(ctx, c, typ, first); err != nil {
		return kexResult{err: err}
	}
	b, err := readPlain(ctx, c)
	if err != nil {
		return kexResult{err: err}
	}
	var res mt.ResPQ
	if err := res.Decode(b); err != nil {
		return kexResult{err: err}
	}
	if res.Nonce != nonce {
		return kexResult{err: errors.New("respq nonce")}
	}
	if f == cRepeat {
		nonce = i128(src)
		if err := writePlain(ctx, c, typ, &mt.ReqPqMultiRequest{Nonce: nonce}); err != nil {
			return kexResult{err: err}
		}
		if b, err = readPlain(ctx, c); err != nil {
			return kexResult{err: err}
		}
		if err := res.Decode(b); err != nil {
			return kexResult{err: err}
		}
		if res.Nonce != nonce {
			return kexResult{err: errors.New("second respq nonce")}
		}
	}
	if f == cEncryptedSecond {
		if err := c.Send(ctx, &bin.Buffer{Buf: encryptedFrame(src)}); err != nil {
			return kexResult{err: err}
		}
		select {
		case <-ctx.Done():
		case <-c.closed:
		}
		return kexResult{err: errors.New("done")}
	}
	fp := refcrypto.RSAFingerprint(&key.PublicKey)
	found := false
	for _, v := range res.ServerPublicKeyFingerprints {
		found = found || v == fp
	}
	if !found {
		return kexResult{err: errors.New("server fingerprint not listed")}
	}
	pq := new(big.Int).SetBytes(res.Pq)
	p, q, err := refcrypto.DecomposePQ(pq, src)
	if err != nil {
		return kexResult{err: err}
	}
	newNonce := i256(src)
	innerDC := dc
	if f == cWrongDC || f == cWrongDCTemp {
		innerDC = dc + 1
	}
	var inner bin.Encoder = &mt.PQInnerDataDC{Pq: res.Pq, P: p.Bytes(), Q: q.Bytes(), Nonce: nonce,
		ServerNonce: res.ServerNonce, NewNonce: newNonce, DC: innerDC}
	if f == cTemp || f == cWrongDCTemp {
		inner = &mt.PQInnerDataTempDC{Pq: res.Pq, P: p.Bytes(), Q: q.Bytes(), Nonce: nonce,
			ServerNonce: res.ServerNonce, NewNonce: newNonce, DC: innerDC, ExpiresIn: 600}
	}
	ib := new(bin.Buffer)
	if err := inner.Encode(ib); err != nil {
		return kexResult{err: err}
	}
	padKey := &key.PublicKey
	if f == cWrongRSA {
		padKey = &privKeys[5].PublicKey
	}
	enc, err := refcrypto.RSAPad(ib.Buf, padKey, src)
	if err != nil {
		return kexResult{err: err}
	}
	if err := writePlain(ctx, c, typ, &mt.ReqDHParamsRequest{Nonce: nonce, ServerNonce: res.ServerNonce,
		P: p.Bytes(), Q: q.Bytes(), PublicKeyFingerprint: fp, EncryptedData: enc}); err != nil {
		return kexResult{err: err}
	}
	if b, err = readPlain(ctx, c); err != nil {
		return kexResult{err: err}
	}
	params, err := mt.DecodeServerDHParams(b)
	if err != nil {
		return kexResult{err: err}
	}
	ok, isOK := params.(*mt.ServerDHParamsOk)
	if !isOK {
		return kexResult{err: fmt.Errorf("server params %T", params)}
	}
	if ok.Nonce != nonce || ok.ServerNonce != res.ServerNonce {
		return kexResult{err: errors.New("server params nonce")}
	}
	tk, tiv := refcrypto.TempAESKeys(newNonce.BigInt(), res.ServerNonce.BigInt())
	dec, err := refcrypto.DecryptExchangeAnswer(ok.EncryptedAnswer, tk, tiv)
	if err != nil || dec == nil {
		return kexResult{err: errors.New("server answer")}
	}
	var sdh mt.ServerDHInnerData
	if err := sdh.Decode(&bin.Buffer{Buf: dec}); err != nil {
		return kexResult{err: err}
	}
	if sdh.Nonce != nonce || sdh.ServerNonce != res.ServerNonce {
		return kexResult{err: errors.New("server inner nonce")}
	}
	dhPrime := new(big.Int).SetBytes(sdh.DhPrime)
	if err := refcrypto.CheckDH(sdh.G, dhPrime); err != nil {
		return kexResult{err: fmt.Errorf("server dh: %w", err)}
	}
	g := big.NewInt(int64(sdh.G))
	ga := new(big.Int).SetBytes(sdh.GA)
	bExp, err := crand.Int(src, new(big.Int).Lsh(big.NewInt(1), 2048))
	if err != nil {
		return kexResult{err: err}
	}
	gb := new(big.Int).Exp(g, bExp, dhPrime)
	if err := refcrypto.CheckDHParams(dhPrime, g, ga, gb); err != nil {
		return kexResult{err: fmt.Errorf("server g_a: %w", err)}
	}
	cdh := mt.ClientDHInnerData{Nonce: nonce, ServerNonce: res.ServerNonce, GB: gb.Bytes()}
	cb := new(bin.Buffer)
	if err := cdh.Encode(cb); err != nil {
		return kexResult{err: err}
	}
	encDH, err := refcrypto.EncryptExchangeAnswer(src, cb.Buf, tk, tiv)
	if err != nil {
		return kexResult{err: err}
	}
	switch f {
	case cGarbageDH:
		encDH = randBytes(src, len(encDH))
	case cUnalignedDH:
		encDH = encDH[:len(encDH)-7]
	}
	if err := writePlain(ctx, c, typ, &mt.SetClientDHParamsRequest{Nonce: nonce, ServerNonce: res.ServerNonce,
		EncryptedData: encDH}); err != nil {
		return kexResult{err: err}
	}
	if b, err = readPlain(ctx, c); err != nil {
		return kexResult{err: err}
	}
	ans, err := mt.DecodeSetClientDHParamsAnswer(b)
	if err != nil {
		return kexResult{err: err}
	}
	gen, isGen := ans.(*mt.DhGenOk)
	if !isGen {
		return kexResult{err: fmt.Errorf("answer %T", ans)}
	}
	var authKey refcrypto.Key
	if !refcrypto.FillBytes(new(big.Int).Exp(ga, bExp, dhPrime), authKey[:]) {
		return kexResult{err: errors.New("auth key size")}
	}
	if gen.Nonce != nonce || gen.ServerNonce != res.ServerNonce || gen.NewNonceHash1 != refcrypto.NonceHash1(newNonce, authKey) {
		return kexResult{err: errors.New("dh_gen_ok fields")}
	}
	return kexResult{val: scriptedResult{key: authKey, salt: refcrypto.ServerSalt(newNonce, res.ServerNonce)}}
}
