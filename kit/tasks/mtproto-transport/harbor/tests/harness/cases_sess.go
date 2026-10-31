package main

// Session-layer cases: the agent's mtproto.Conn (with its rpc engine, salts and the lower layers) against a
// scripted server built from reference primitives. Outputs are observations that do not depend on timing or
// on how randomness is consumed: decoded results, error kinds, and properties of the messages the server saw.

import (
	"context"
	"crypto/rsa"
	"errors"
	"fmt"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/gotd/td/bin"
	"github.com/gotd/td/clock"
	agcrypto "github.com/gotd/td/crypto"
	agex "github.com/gotd/td/exchange"
	refcrypto "github.com/gotd/td/internal/zref/crypto"
	refex "github.com/gotd/td/internal/zref/exchange"
	"github.com/gotd/td/mt"
	"github.com/gotd/td/mtproto"
	agcodec "github.com/gotd/td/proto/codec"
	"github.com/gotd/td/proto"
	"github.com/gotd/td/rpc"
	"github.com/gotd/td/tg"
	"github.com/gotd/td/tgerr"
	"github.com/gotd/td/transport"

	"github.com/gotd/ige"
	"encoding/binary"
)

type transportConn = transport.Conn

func decryptBindEnvelope(k refcrypto.Key, enc []byte) []byte {
	var mk bin.Int128
	copy(mk[:], enc[8:24])
	key, iv := refcrypto.KeysV1(k, mk)
	pt := make([]byte, len(enc)-24)
	ige.DecryptAES256Blocks(key[:], iv[:], pt, enc[24:])
	return pt
}

// checkBindRaw verifies the binding envelope without knowing the inner message in advance.
func checkBindRaw(k refcrypto.Key, msgID int64, enc []byte) error {
	if (len(enc)-24)%16 != 0 || len(enc) < 24+32 {
		return errors.New("bad length")
	}
	id := k.ID()
	if string(enc[:8]) != string(id[:]) {
		return errors.New("bad key id")
	}
	pt := decryptBindEnvelope(k, enc)
	n := int(binary.LittleEndian.Uint32(pt[28:32]))
	if n < 0 || 32+n > len(pt) || len(pt)-(32+n) >= 16 {
		return errors.New("bad envelope length")
	}
	var mk bin.Int128
	copy(mk[:], enc[8:24])
	if refcrypto.MessageKeyV1(pt[:32+n]) != mk {
		return errors.New("bad msg_key")
	}
	if int64(binary.LittleEndian.Uint64(pt[16:24])) != msgID || binary.LittleEndian.Uint32(pt[24:28]) != 0 {
		return errors.New("bad msg_id or seq_no")
	}
	return nil
}

// cmsg is one client message as the server saw it (containers expanded, gzip unpacked).
type cmsg struct {
	id, session, salt int64
	seq               int32
	typ               uint32
	body              []byte
	gz, contained     bool
	keyID             [8]byte
}

type sessSrv struct {
	c       *msgConn
	priv    *rsa.PrivateKey
	key     refcrypto.AuthKey
	perm    refcrypto.AuthKey
	salt    int64
	session int64
	cipher  refcrypto.Cipher
	ids     *proto.MessageIDGen
	content int32
	queue   []cmsg
	log     []cmsg
	src     interface{ Read([]byte) (int, error) }
}

func newSessSrv(c *msgConn, priv *rsa.PrivateKey, id string) *sessSrv {
	return &sessSrv{
		c: c, priv: priv,
		cipher: refcrypto.NewServerCipher(rng(id, "srvcipher")),
		ids:    proto.NewMessageIDGen(time.Now),
		src:    rng(id, "srv"),
	}
}

// exchange runs a reference server key exchange on the connection.
func (s *sessSrv) exchange(ctx context.Context, id string, n int) error {
	ex := refex.NewExchanger(s.c, 2).WithRand(rng(id, "kex", itoa(n))).WithClock(clock.System).
		WithTimeout(20 * time.Second).Server(refex.PrivateKey{RSA: s.priv})
	r, err := ex.Run(ctx)
	if err != nil {
		return fmt.Errorf("server exchange: %w", err)
	}
	s.key, s.salt, s.session = r.Key, r.ServerSalt, 0
	return nil
}

func (s *sessSrv) push(m cmsg) {
	s.queue = append(s.queue, m)
	s.log = append(s.log, m)
}

func (s *sessSrv) expand(m cmsg) {
	b := &bin.Buffer{Buf: m.body}
	id, err := b.PeekID()
	if err != nil {
		m.typ = 0
		s.push(m)
		return
	}
	switch id {
	case proto.MessageContainerTypeID:
		var c proto.MessageContainer
		if err := c.Decode(b); err != nil {
			m.typ = id
			s.push(m)
			return
		}
		for _, in := range c.Messages {
			s.expand(cmsg{id: in.ID, seq: int32(in.SeqNo), session: m.session, salt: m.salt, body: in.Body,
				contained: true, keyID: m.keyID})
		}
		return
	case proto.GZIPTypeID:
		var g proto.GZIP
		if err := g.Decode(b); err == nil {
			m.body, m.gz = g.Data, true
			if t, err := (&bin.Buffer{Buf: m.body}).PeekID(); err == nil {
				id = t
			}
		}
	}
	m.typ = id
	s.push(m)
}

// next returns the next client message, reading and decrypting frames as needed.
func (s *sessSrv) next(ctx context.Context) (cmsg, error) {
	for len(s.queue) == 0 {
		b := new(bin.Buffer)
		if err := s.c.Recv(ctx, b); err != nil {
			return cmsg{}, err
		}
		var keyID [8]byte
		copy(keyID[:], b.Buf)
		d, err := s.cipher.DecryptFromBuffer(s.key, &bin.Buffer{Buf: append([]byte(nil), b.Buf...)})
		if err != nil {
			s.push(cmsg{typ: 0xffffffff, keyID: keyID})
			continue
		}
		if s.session == 0 {
			s.session = d.SessionID
		}
		s.expand(cmsg{id: d.MessageID, seq: d.SeqNo, session: d.SessionID, salt: d.Salt,
			body: append([]byte(nil), d.Data()...), keyID: keyID})
	}
	m := s.queue[0]
	s.queue = s.queue[1:]
	return m, nil
}

func (s *sessSrv) waitType(ctx context.Context, typ uint32) (cmsg, error) {
	for {
		m, err := s.next(ctx)
		if err != nil {
			return m, err
		}
		if m.typ == typ {
			return m, nil
		}
	}
}

func (s *sessSrv) sendData(ctx context.Context, d refcrypto.EncryptedMessageData) error {
	b := new(bin.Buffer)
	if err := s.cipher.Encrypt(s.key, d, b); err != nil {
		return err
	}
	return s.c.Send(ctx, b)
}

// send sends msg as a server message; content messages get odd seq_no.
func (s *sessSrv) send(ctx context.Context, msg bin.Encoder, content bool, typ proto.MessageType) (int64, error) {
	id := s.ids.New(typ)
	seq := s.content * 2
	if content {
		seq++
		s.content++
	}
	return id, s.sendData(ctx, refcrypto.EncryptedMessageData{Salt: s.salt, SessionID: s.session, MessageID: id,
		SeqNo: seq, Message: msg})
}

func encodeTL(m bin.Encoder) []byte {
	b := new(bin.Buffer)
	if err := m.Encode(b); err != nil {
		panic(err)
	}
	return b.Buf
}

func (s *sessSrv) result(ctx context.Context, reqID int64, m bin.Encoder) error {
	_, err := s.send(ctx, &proto.Result{RequestMessageID: reqID, Result: encodeTL(m)}, true, proto.MessageServerResponse)
	return err
}

func (s *sessSrv) ack(ctx context.Context, ids ...int64) error {
	_, err := s.send(ctx, &mt.MsgsAck{MsgIDs: ids}, false, proto.MessageServerResponse)
	return err
}

func username(m cmsg) string {
	var req tg.AccountCheckUsernameRequest
	if err := req.Decode(&bin.Buffer{Buf: m.body}); err != nil {
		return "?"
	}
	return req.Username
}

func boolFor(name string) bin.Encoder {
	if len(name)%2 == 0 {
		return &tg.BoolTrue{}
	}
	return &tg.BoolFalse{}
}

// checkLog verifies properties of every message the client sent under one key.
func checkLog(log []cmsg, salts map[int64]bool) string {
	var ok []string
	seen := map[int64]bool{}
	var reqs []cmsg
	idsOK, sessOK, saltOK := true, true, true
	var session int64
	for _, m := range log {
		if m.typ == 0xffffffff {
			continue
		}
		if m.id%4 != 0 || (seen[m.id] && m.typ != tg.AccountCheckUsernameRequestTypeID) {
			idsOK = false
		}
		seen[m.id] = true
		if session == 0 {
			session = m.session
		}
		if m.session != session {
			sessOK = false
		}
		if salts != nil && !salts[m.salt] {
			saltOK = false
		}
		if m.typ == tg.AccountCheckUsernameRequestTypeID {
			reqs = append(reqs, m)
		}
	}
	sort.Slice(reqs, func(i, j int) bool { return reqs[i].id < reqs[j].id })
	seqOK := true
	k := int32(0)
	var last int64
	for _, r := range reqs {
		if r.id == last {
			continue // a resend keeps its msg_id and seq_no
		}
		last = r.id
		if r.seq != 2*k+1 {
			seqOK = false
		}
		k++
	}
	ok = append(ok, fmt.Sprintf("ids=%v", idsOK), fmt.Sprintf("session=%v", sessOK && session != 0),
		fmt.Sprintf("seq=%v", seqOK))
	if salts != nil {
		ok = append(ok, fmt.Sprintf("salt=%v", saltOK))
	}
	return strings.Join(ok, ",")
}

type recHandler struct {
	mu       sync.Mutex
	sessions []int64
	types    []uint32
}

func (h *recHandler) OnMessage(b *bin.Buffer) error {
	id, _ := b.PeekID()
	h.mu.Lock()
	h.types = append(h.types, id)
	h.mu.Unlock()
	return nil
}

func (h *recHandler) OnSession(s mtproto.Session) error {
	h.mu.Lock()
	h.sessions = append(h.sessions, s.Salt)
	h.mu.Unlock()
	return nil
}

func (h *recHandler) snapshot() ([]int64, []uint32) {
	h.mu.Lock()
	defer h.mu.Unlock()
	return append([]int64(nil), h.sessions...), append([]uint32(nil), h.types...)
}

type sessOpts struct {
	pfs          bool
	restore      bool
	retry        time.Duration
	maxRetries   int
	compress     int
	dialFail     bool
	noExchange   bool
	runErrWanted bool
}

// runSess runs one scenario: the server script and the client function concurrently.
func runSess(id string, o sessOpts, script func(ctx context.Context, s *sessSrv) string,
	client func(ctx context.Context, c *mtproto.Conn, h *recHandler) string) string {
	loadData()
	priv := privKeys[3]
	a, b := msgPipe()
	srv := newSessSrv(b, priv, id)
	h := &recHandler{}
	opts := mtproto.Options{
		DC:                2,
		PublicKeys:        []agex.PublicKey{{RSA: &priv.PublicKey}},
		Random:            rng(id, "client"),
		Handler:           h,
		AckInterval:       100 * time.Millisecond,
		AckBatchSize:      20,
		RetryInterval:     o.retry,
		MaxRetries:        o.maxRetries,
		PingInterval:      time.Hour,
		PingTimeout:       20 * time.Second,
		SaltFetchInterval: time.Hour,
		DialTimeout:       40 * time.Second,
		ExchangeTimeout:   20 * time.Second,
		CompressThreshold: o.compress,
		EnablePFS:         o.pfs,
	}
	if opts.RetryInterval == 0 {
		opts.RetryInterval = 4 * time.Second
	}
	if o.restore {
		var k refcrypto.Key
		copy(k[:], randBytes(rng(id, "restore"), 256))
		srv.key = k.WithID()
		srv.salt = int64(prng(id, "salt").Uint64())
		opts.Key = agcrypto.AuthKey{Value: agcrypto.Key(k), ID: k.ID()}
		opts.Salt = srv.salt
	}
	ctx, cancel := context.WithTimeout(context.Background(), 50*time.Second)
	defer cancel()
	dialed := false
	dialer := func(ctx context.Context) (_ transportConn, err error) {
		if o.dialFail || dialed {
			return nil, errors.New("dial refused")
		}
		dialed = true
		return a, nil
	}
	srvOut := make(chan string, 1)
	go func() {
		defer func() {
			if r := recover(); r != nil {
				srvOut <- fmt.Sprintf("server panic: %v", r)
			}
		}()
		if !o.restore && !o.dialFail && !o.noExchange {
			if err := srv.exchange(ctx, id, 0); err != nil {
				srvOut <- "exchange: " + errKind(err)
				return
			}
		}
		srvOut <- script(ctx, srv)
	}()
	conn := mtproto.New(mtproto.Dialer(dialer), opts)
	cliOut := make(chan string, 1)
	runErr := make(chan error, 1)
	go func() {
		defer func() {
			if r := recover(); r != nil {
				cliOut <- fmt.Sprintf("client panic: %v", r)
				runErr <- errors.New("panic")
			}
		}()
		called := false
		err := conn.Run(ctx, func(ctx context.Context) error {
			called = true
			cliOut <- client(ctx, conn, h)
			<-ctx.Done()
			return nil
		})
		if !called {
			cliOut <- "f not called"
		}
		runErr <- err
	}()
	var c, sv string
	select {
	case c = <-cliOut:
	case <-ctx.Done():
		c = "client timeout"
	}
	select {
	case sv = <-srvOut:
	case <-time.After(10 * time.Second):
		sv = "server timeout"
	}
	cancel()
	_ = a.Close()
	select {
	case <-runErr:
	case <-time.After(10 * time.Second):
		c += "|run did not return"
	}
	return join("client:"+c, "server:"+sv)
}

func errKind(err error) string {
	if err == nil {
		return "nil"
	}
	if e, ok := tgerr.As(err); ok {
		return fmt.Sprintf("rpc %d %s %d", e.Code, e.Type, e.Argument)
	}
	if errors.Is(err, &rpc.RetryLimitReachedErr{}) {
		return "retry-limit"
	}
	return "err"
}

func invoke(ctx context.Context, c *mtproto.Conn, name string) string {
	var res tg.BoolBox
	ictx, cancel := context.WithTimeout(ctx, 25*time.Second)
	defer cancel()
	if err := c.Invoke(ictx, &tg.AccountCheckUsernameRequest{Username: name}, &res); err != nil {
		return errKind(err)
	}
	switch res.Bool.(type) {
	case *tg.BoolTrue:
		return "true"
	case *tg.BoolFalse:
		return "false"
	}
	return "?"
}

func registerSess() {
	const T = 60 * time.Second
	// Plain requests: results, msg_id / seq_no / session / salt discipline.
	for i := 0; i < 6; i++ {
		id := fmt.Sprintf("sess/basic/%d", i)
		n := 1 + i%3
		addT(id, T, func() string {
			return runSess(id, sessOpts{}, func(ctx context.Context, s *sessSrv) string {
				for k := 0; k < n; k++ {
					m, err := s.waitType(ctx, tg.AccountCheckUsernameRequestTypeID)
					if err != nil {
						return "wait: " + errKind(err)
					}
					if err := s.result(ctx, m.id, boolFor(username(m))); err != nil {
						return "send"
					}
				}
				return checkLog(s.log, map[int64]bool{s.salt: true})
			}, func(ctx context.Context, c *mtproto.Conn, h *recHandler) string {
				var out []string
				for k := 0; k < n; k++ {
					out = append(out, invoke(ctx, c, fmt.Sprintf("user%0*d", 1+k+i, k)))
				}
				return strings.Join(out, ",")
			})
		})
	}

	// new_session_created changes the salt and reaches Handler.OnSession.
	for i := 0; i < 3; i++ {
		id := fmt.Sprintf("sess/newsession/%d", i)
		inContainer := i == 2
		addT(id, T, func() string {
			newSalt := int64(prng(id).Uint64())
			return runSess(id, sessOpts{}, func(ctx context.Context, s *sessSrv) string {
				m, err := s.waitType(ctx, tg.AccountCheckUsernameRequestTypeID)
				if err != nil {
					return "wait"
				}
				old := s.salt
				ns := &mt.NewSessionCreated{FirstMsgID: m.id, UniqueID: int64(prng(id, "u").Uint64()), ServerSalt: newSalt}
				if inContainer {
					res := &proto.Result{RequestMessageID: m.id, Result: encodeTL(boolFor(username(m)))}
					cont := &proto.MessageContainer{Messages: []proto.Message{
						{ID: s.ids.New(proto.MessageFromServer), SeqNo: int(2*s.content + 1), Body: encodeTL(ns)},
						{ID: s.ids.New(proto.MessageServerResponse), SeqNo: int(2*s.content + 3), Body: encodeTL(res)},
					}}
					for k := range cont.Messages {
						cont.Messages[k].Bytes = len(cont.Messages[k].Body)
					}
					s.content += 2
					s.salt = newSalt
					if _, err := s.send(ctx, cont, false, proto.MessageServerResponse); err != nil {
						return "send"
					}
				} else {
					s.salt = newSalt
					if _, err := s.send(ctx, ns, true, proto.MessageFromServer); err != nil {
						return "send"
					}
					time.Sleep(300 * time.Millisecond)
					if err := s.result(ctx, m.id, boolFor(username(m))); err != nil {
						return "send"
					}
				}
				m2, err := s.waitType(ctx, tg.AccountCheckUsernameRequestTypeID)
				if err != nil {
					return "wait2"
				}
				if err := s.result(ctx, m2.id, boolFor(username(m2))); err != nil {
					return "send"
				}
				return fmt.Sprintf("first=%v second=%v", m.salt == old, m2.salt == newSalt)
			}, func(ctx context.Context, c *mtproto.Conn, h *recHandler) string {
				r1 := invoke(ctx, c, "alpha")
				time.Sleep(500 * time.Millisecond)
				r2 := invoke(ctx, c, "betaa")
				sessions, _ := h.snapshot()
				got := len(sessions) > 0 && sessions[len(sessions)-1] == newSalt
				return fmt.Sprintf("%s,%s,onsession=%v", r1, r2, got)
			})
		})
	}

	// bad_server_salt: the request is sent again with the new salt.
	for i := 0; i < 3; i++ {
		id := fmt.Sprintf("sess/badsalt/%d", i)
		addT(id, T, func() string {
			newSalt := int64(prng(id).Uint64())
			return runSess(id, sessOpts{}, func(ctx context.Context, s *sessSrv) string {
				m, err := s.waitType(ctx, tg.AccountCheckUsernameRequestTypeID)
				if err != nil {
					return "wait"
				}
				if _, err := s.send(ctx, &mt.BadServerSalt{BadMsgID: m.id, BadMsgSeqno: int(m.seq), ErrorCode: 48,
					NewServerSalt: newSalt}, false, proto.MessageServerResponse); err != nil {
					return "send"
				}
				s.salt = newSalt
				m2, err := s.waitType(ctx, tg.AccountCheckUsernameRequestTypeID)
				if err != nil {
					return "wait2"
				}
				if err := s.result(ctx, m2.id, boolFor(username(m2))); err != nil {
					return "send"
				}
				return fmt.Sprintf("resent=%v newsalt=%v", username(m2) == username(m), m2.salt == newSalt)
			}, func(ctx context.Context, c *mtproto.Conn, h *recHandler) string {
				return invoke(ctx, c, fmt.Sprintf("salty%d", i))
			})
		})
	}

	// bad_msg_notification fails the request; the connection keeps working.
	for _, code := range []int{16, 17, 32, 33} {
		id := fmt.Sprintf("sess/badmsg/%d", code)
		code := code
		addT(id, T, func() string {
			return runSess(id, sessOpts{}, func(ctx context.Context, s *sessSrv) string {
				m, err := s.waitType(ctx, tg.AccountCheckUsernameRequestTypeID)
				if err != nil {
					return "wait"
				}
				if _, err := s.send(ctx, &mt.BadMsgNotification{BadMsgID: m.id, BadMsgSeqno: int(m.seq), ErrorCode: code},
					false, proto.MessageServerResponse); err != nil {
					return "send"
				}
				m2, err := s.waitType(ctx, tg.AccountCheckUsernameRequestTypeID)
				if err != nil {
					return "wait2"
				}
				if username(m2) == username(m) {
					return "resent"
				}
				if err := s.result(ctx, m2.id, boolFor(username(m2))); err != nil {
					return "send"
				}
				return "ok"
			}, func(ctx context.Context, c *mtproto.Conn, h *recHandler) string {
				r1 := invoke(ctx, c, "first")
				r2 := invoke(ctx, c, "second")
				return r1 + "," + r2
			})
		})
	}

	// rpc_error, plain and gzip-packed results, and results inside containers.
	for i, e := range []mt.RPCError{{ErrorCode: 400, ErrorMessage: "USERNAME_INVALID"},
		{ErrorCode: 420, ErrorMessage: "FLOOD_WAIT_17"}, {ErrorCode: 303, ErrorMessage: "USER_MIGRATE_4"}} {
		id := fmt.Sprintf("sess/rpcerror/%d", i)
		e := e
		addT(id, T, func() string {
			return runSess(id, sessOpts{}, func(ctx context.Context, s *sessSrv) string {
				m, err := s.waitType(ctx, tg.AccountCheckUsernameRequestTypeID)
				if err != nil {
					return "wait"
				}
				if err := s.result(ctx, m.id, &e); err != nil {
					return "send"
				}
				return "ok"
			}, func(ctx context.Context, c *mtproto.Conn, h *recHandler) string {
				return invoke(ctx, c, "errs")
			})
		})
	}
	for i := 0; i < 4; i++ {
		id := fmt.Sprintf("sess/packed/%d", i)
		i := i
		addT(id, T, func() string {
			return runSess(id, sessOpts{}, func(ctx context.Context, s *sessSrv) string {
				m, err := s.waitType(ctx, tg.AccountCheckUsernameRequestTypeID)
				if err != nil {
					return "wait"
				}
				var body bin.Encoder = boolFor(username(m))
				if i%2 == 1 {
					body = &mt.RPCError{ErrorCode: 400, ErrorMessage: "PACKED_ERROR"}
				}
				res := &proto.Result{RequestMessageID: m.id, Result: encodeTL(&proto.GZIP{Data: encodeTL(body)})}
				if i >= 2 {
					cont := &proto.MessageContainer{Messages: []proto.Message{
						{ID: s.ids.New(proto.MessageServerResponse), SeqNo: int(2 * s.content), Body: encodeTL(&mt.MsgsAck{MsgIDs: []int64{m.id}})},
						{ID: s.ids.New(proto.MessageServerResponse), SeqNo: int(2*s.content + 1), Body: encodeTL(res)},
					}}
					for k := range cont.Messages {
						cont.Messages[k].Bytes = len(cont.Messages[k].Body)
					}
					s.content++
					_, err = s.send(ctx, cont, false, proto.MessageServerResponse)
				} else {
					_, err = s.send(ctx, &proto.GZIP{Data: encodeTL(res)}, true, proto.MessageServerResponse)
				}
				if err != nil {
					return "send"
				}
				return "ok"
			}, func(ctx context.Context, c *mtproto.Conn, h *recHandler) string {
				return invoke(ctx, c, "gzipme")
			})
		})
	}

	// Content messages from the server are acknowledged; updates reach the handler once.
	for i := 0; i < 3; i++ {
		id := fmt.Sprintf("sess/ack/%d", i)
		i := i
		addT(id, T, func() string {
			return runSess(id, sessOpts{}, func(ctx context.Context, s *sessSrv) string {
				m, err := s.waitType(ctx, tg.AccountCheckUsernameRequestTypeID)
				if err != nil {
					return "wait"
				}
				var upd []int64
				for k := 0; k < 1+i; k++ {
					uid, err := s.send(ctx, &tg.UpdatesTooLong{}, true, proto.MessageFromServer)
					if err != nil {
						return "send"
					}
					upd = append(upd, uid)
				}
				if err := s.result(ctx, m.id, boolFor(username(m))); err != nil {
					return "send"
				}
				want := map[int64]bool{}
				for _, u := range upd {
					want[u] = true
				}
				deadline := time.Now().Add(8 * time.Second)
				dctx, cancel := context.WithDeadline(ctx, deadline)
				defer cancel()
				for len(want) > 0 {
					a, err := s.waitType(dctx, mt.MsgsAckTypeID)
					if err != nil {
						return fmt.Sprintf("unacked=%d", len(want))
					}
					var ack mt.MsgsAck
					if err := ack.Decode(&bin.Buffer{Buf: a.body}); err != nil {
						return "badack"
					}
					if a.seq%2 != 0 {
						return "ack is content"
					}
					for _, x := range ack.MsgIDs {
						delete(want, x)
					}
				}
				return "acked"
			}, func(ctx context.Context, c *mtproto.Conn, h *recHandler) string {
				r := invoke(ctx, c, "acker")
				time.Sleep(1500 * time.Millisecond)
				_, types := h.snapshot()
				cnt := 0
				for _, t := range types {
					if t == tg.UpdatesTooLongTypeID {
						cnt++
					}
				}
				return fmt.Sprintf("%s,updates=%d", r, cnt)
			})
		})
	}

	// Messages the client must ignore: duplicates, wrong session, stale or wrongly typed msg_id.
	addT("sess/ignore", T, func() string {
		id := "sess/ignore"
		return runSess(id, sessOpts{}, func(ctx context.Context, s *sessSrv) string {
			m, err := s.waitType(ctx, tg.AccountCheckUsernameRequestTypeID)
			if err != nil {
				return "wait"
			}
			upd := encodeTL(&tg.UpdatesTooLong{})
			mk := func(msgID int64, session int64) refcrypto.EncryptedMessageData {
				return refcrypto.EncryptedMessageData{Salt: s.salt, SessionID: session, MessageID: msgID, SeqNo: 2*s.content + 1,
					MessageDataLen: int32(len(upd)), MessageDataWithPadding: upd}
			}
			good := s.ids.New(proto.MessageFromServer)
			sends := []refcrypto.EncryptedMessageData{
				mk(good, s.session),
				mk(good, s.session), // duplicate
				mk(s.ids.New(proto.MessageFromServer), s.session+1),                                    // wrong session
				mk(int64(proto.NewMessageID(time.Now().Add(-10*time.Minute), proto.MessageFromServer)), s.session), // too old
				mk(int64(proto.NewMessageID(time.Now().Add(2*time.Minute), proto.MessageFromServer)), s.session),   // too far ahead
				mk(int64(proto.NewMessageID(time.Now(), proto.MessageFromClient)), s.session),                     // client type
			}
			s.content++
			for _, d := range sends {
				if err := s.sendData(ctx, d); err != nil {
					return "send"
				}
				time.Sleep(50 * time.Millisecond)
			}
			if err := s.result(ctx, m.id, boolFor(username(m))); err != nil {
				return "send"
			}
			return "ok"
		}, func(ctx context.Context, c *mtproto.Conn, h *recHandler) string {
			r := invoke(ctx, c, "ignorer")
			time.Sleep(1500 * time.Millisecond)
			_, types := h.snapshot()
			return fmt.Sprintf("%s,handled=%d", r, len(types))
		})
	})

	// Retries: resend with the same msg_id until acknowledged; no resend after an ack; retry limit.
	addT("sess/retry/resend", T, func() string {
		id := "sess/retry/resend"
		return runSess(id, sessOpts{retry: 700 * time.Millisecond, maxRetries: 6}, func(ctx context.Context, s *sessSrv) string {
			m, err := s.waitType(ctx, tg.AccountCheckUsernameRequestTypeID)
			if err != nil {
				return "wait"
			}
			m2, err := s.waitType(ctx, tg.AccountCheckUsernameRequestTypeID)
			if err != nil {
				return "no resend"
			}
			if err := s.result(ctx, m2.id, boolFor(username(m2))); err != nil {
				return "send"
			}
			return fmt.Sprintf("sameid=%v sameseq=%v", m2.id == m.id, m2.seq == m.seq)
		}, func(ctx context.Context, c *mtproto.Conn, h *recHandler) string {
			return invoke(ctx, c, "again!")
		})
	})
	addT("sess/retry/acked", T, func() string {
		id := "sess/retry/acked"
		return runSess(id, sessOpts{retry: 500 * time.Millisecond, maxRetries: 6}, func(ctx context.Context, s *sessSrv) string {
			m, err := s.waitType(ctx, tg.AccountCheckUsernameRequestTypeID)
			if err != nil {
				return "wait"
			}
			if err := s.ack(ctx, m.id); err != nil {
				return "send"
			}
			time.Sleep(2500 * time.Millisecond)
			if err := s.result(ctx, m.id, boolFor(username(m))); err != nil {
				return "send"
			}
			n := 0
			for _, x := range s.log {
				if x.typ == tg.AccountCheckUsernameRequestTypeID {
					n++
				}
			}
			return fmt.Sprintf("transmissions=%d", n)
		}, func(ctx context.Context, c *mtproto.Conn, h *recHandler) string {
			return invoke(ctx, c, "ackfirst")
		})
	})
	addT("sess/retry/limit", T, func() string {
		id := "sess/retry/limit"
		return runSess(id, sessOpts{retry: 300 * time.Millisecond, maxRetries: 3}, func(ctx context.Context, s *sessSrv) string {
			_, err := s.waitType(ctx, tg.AccountCheckUsernameRequestTypeID)
			if err != nil {
				return "wait"
			}
			return "silent"
		}, func(ctx context.Context, c *mtproto.Conn, h *recHandler) string {
			return invoke(ctx, c, "nobody")
		})
	})

	// Ping / pong.
	addT("sess/ping", T, func() string {
		id := "sess/ping"
		return runSess(id, sessOpts{}, func(ctx context.Context, s *sessSrv) string {
			m, err := s.waitType(ctx, mt.PingRequestTypeID)
			if err != nil {
				return "wait"
			}
			var p mt.PingRequest
			if err := p.Decode(&bin.Buffer{Buf: m.body}); err != nil {
				return "decode"
			}
			if _, err := s.send(ctx, &mt.Pong{MsgID: m.id, PingID: p.PingID}, false, proto.MessageServerResponse); err != nil {
				return "send"
			}
			return fmt.Sprintf("even=%v", m.seq%2 == 0)
		}, func(ctx context.Context, c *mtproto.Conn, h *recHandler) string {
			pctx, cancel := context.WithTimeout(ctx, 20*time.Second)
			defer cancel()
			return errKind(c.Ping(pctx))
		})
	})

	// Large requests are sent gzip-packed above CompressThreshold (never when it is negative).
	for i, thr := range []int{0, 0, -1, 5000} {
		id := fmt.Sprintf("sess/compress/%d", i)
		thr, size := thr, []int{3000, 200, 3000, 3000}[i]
		addT(id, T, func() string {
			return runSess(id, sessOpts{compress: thr}, func(ctx context.Context, s *sessSrv) string {
				m, err := s.waitType(ctx, tg.AccountCheckUsernameRequestTypeID)
				if err != nil {
					return "wait"
				}
				if err := s.result(ctx, m.id, boolFor(username(m))); err != nil {
					return "send"
				}
				return fmt.Sprintf("gzip=%v len=%d", m.gz, len(username(m)))
			}, func(ctx context.Context, c *mtproto.Conn, h *recHandler) string {
				return invoke(ctx, c, strings.Repeat("z", size))
			})
		})
	}

	// future_salts: requested after new_session_created; the stored salt is used.
	addT("sess/futuresalts", T, func() string {
		id := "sess/futuresalts"
		fut := int64(prng(id).Uint64())
		return runSess(id, sessOpts{}, func(ctx context.Context, s *sessSrv) string {
			m, err := s.waitType(ctx, tg.AccountCheckUsernameRequestTypeID)
			if err != nil {
				return "wait"
			}
			if _, err := s.send(ctx, &mt.NewSessionCreated{FirstMsgID: m.id, UniqueID: 7, ServerSalt: s.salt}, true,
				proto.MessageFromServer); err != nil {
				return "send"
			}
			g, err := s.waitType(ctx, mt.GetFutureSaltsRequestTypeID)
			if err != nil {
				return "no get_future_salts"
			}
			now := int(time.Now().Unix())
			fs := &mt.FutureSalts{ReqMsgID: g.id, Now: now, Salts: []mt.FutureSalt{
				{ValidSince: now - 60, ValidUntil: now + 3600, Salt: fut},
				{ValidSince: now - 3600, ValidUntil: now + 60, Salt: fut + 1},
			}}
			if _, err := s.send(ctx, fs, false, proto.MessageServerResponse); err != nil {
				return "send"
			}
			time.Sleep(400 * time.Millisecond)
			if err := s.result(ctx, m.id, boolFor(username(m))); err != nil {
				return "send"
			}
			m2, err := s.waitType(ctx, tg.AccountCheckUsernameRequestTypeID)
			if err != nil {
				return "wait2"
			}
			if err := s.result(ctx, m2.id, boolFor(username(m2))); err != nil {
				return "send"
			}
			return fmt.Sprintf("even=%v futuresalt=%v", g.seq%2 == 0, m2.salt == fut)
		}, func(ctx context.Context, c *mtproto.Conn, h *recHandler) string {
			r1 := invoke(ctx, c, "salt1")
			time.Sleep(300 * time.Millisecond)
			return r1 + "," + invoke(ctx, c, "salt22")
		})
	})

	// A stored key and salt: no exchange, a fresh session id.
	addT("sess/restore", T, func() string {
		id := "sess/restore"
		return runSess(id, sessOpts{restore: true}, func(ctx context.Context, s *sessSrv) string {
			m, err := s.waitType(ctx, tg.AccountCheckUsernameRequestTypeID)
			if err != nil {
				return "wait: " + errKind(err)
			}
			if err := s.result(ctx, m.id, boolFor(username(m))); err != nil {
				return "send"
			}
			return checkLog(s.log, map[int64]bool{s.salt: true})
		}, func(ctx context.Context, c *mtproto.Conn, h *recHandler) string {
			return invoke(ctx, c, "restored")
		})
	})

	// Transport error 404 after the session started: a new key is created on the same connection and the
	// unanswered request is sent again under it.
	addT("sess/rekey", T, func() string {
		id := "sess/rekey"
		return runSess(id, sessOpts{retry: 1500 * time.Millisecond, maxRetries: 10}, func(ctx context.Context, s *sessSrv) string {
			m, err := s.waitType(ctx, tg.AccountCheckUsernameRequestTypeID)
			if err != nil {
				return "wait"
			}
			oldKey := s.key.ID
			s.c.sendErr(&agcodec.ProtocolErr{Code: 404})
			s.queue = nil
			if err := s.exchange(ctx, id, 1); err != nil {
				return "rekey: " + errKind(err)
			}
			for {
				m2, err := s.waitType(ctx, tg.AccountCheckUsernameRequestTypeID)
				if err != nil {
					return "wait2"
				}
				if username(m2) != username(m) {
					return "other request"
				}
				if err := s.result(ctx, m2.id, boolFor(username(m2))); err != nil {
					return "send"
				}
				return fmt.Sprintf("newkey=%v", m2.keyID != oldKey && m2.keyID == s.key.ID)
			}
		}, func(ctx context.Context, c *mtproto.Conn, h *recHandler) string {
			return invoke(ctx, c, "rekeyed")
		})
	})

	// PFS: permanent key, temporary key, auth.bindTempAuthKey, then requests under the temporary key.
	for _, accept := range []bool{true, false} {
		id := fmt.Sprintf("sess/pfs/%v", accept)
		accept := accept
		addT(id, T, func() string {
			return runSess(id, sessOpts{pfs: true, noExchange: true}, func(ctx context.Context, s *sessSrv) string {
				if err := s.exchange(ctx, id, 0); err != nil {
					return "perm: " + errKind(err)
				}
				s.perm = s.key
				if err := s.exchange(ctx, id, 1); err != nil {
					return "temp: " + errKind(err)
				}
				m, err := s.waitType(ctx, tg.AuthBindTempAuthKeyRequestTypeID)
				if err != nil {
					return "no bind"
				}
				var req tg.AuthBindTempAuthKeyRequest
				if err := req.Decode(&bin.Buffer{Buf: m.body}); err != nil {
					return "bind decode"
				}
				inner, verr := verifyBind(s.perm, m.id, req.EncryptedMessage)
				valid := verr == nil && req.PermAuthKeyID == s.perm.IntID() && inner.PermAuthKeyID == s.perm.IntID() &&
					inner.TempAuthKeyID == s.key.IntID() && inner.Nonce == req.Nonce && inner.TempSessionID == m.session &&
					inner.ExpiresAt == req.ExpiresAt
				var ans bin.Encoder = &tg.BoolTrue{}
				if !accept {
					ans = &tg.BoolFalse{}
				}
				if err := s.result(ctx, m.id, ans); err != nil {
					return "send"
				}
				if !accept {
					return fmt.Sprintf("bind=%v", valid)
				}
				m2, err := s.waitType(ctx, tg.AccountCheckUsernameRequestTypeID)
				if err != nil {
					return "wait2"
				}
				if err := s.result(ctx, m2.id, boolFor(username(m2))); err != nil {
					return "send"
				}
				return fmt.Sprintf("bind=%v tempkey=%v", valid, m2.keyID == s.key.ID)
			}, func(ctx context.Context, c *mtproto.Conn, h *recHandler) string {
				return invoke(ctx, c, "pfsuser")
			})
		})
	}

	// A dial error makes Run fail without calling f.
	// (paired with a working connection in the same case, so that a Run that always fails does not pass it).
	addT("sess/dialfail", 2*T, func() string {
		failed := runSess("sess/dialfail", sessOpts{dialFail: true}, func(ctx context.Context, s *sessSrv) string {
			return "idle"
		}, func(ctx context.Context, c *mtproto.Conn, h *recHandler) string {
			return "called"
		})
		works := runSess("sess/dialfail/control", sessOpts{}, func(ctx context.Context, s *sessSrv) string {
			m, err := s.waitType(ctx, tg.AccountCheckUsernameRequestTypeID)
			if err != nil {
				return "wait"
			}
			if err := s.result(ctx, m.id, boolFor(username(m))); err != nil {
				return "send"
			}
			return "ok"
		}, func(ctx context.Context, c *mtproto.Conn, h *recHandler) string {
			return invoke(ctx, c, "control")
		})
		return failed + "||" + works
	})
}

// verifyBind decrypts a binding message (MTProto 1.0 envelope under the permanent key).
func verifyBind(perm refcrypto.AuthKey, msgID int64, enc []byte) (refcrypto.BindAuthKeyInner, error) {
	var inner refcrypto.BindAuthKeyInner
	if len(enc) < 24 {
		return inner, errors.New("short")
	}
	if res := checkBindRaw(perm.Value, msgID, enc); res != nil {
		return inner, res
	}
	pt := decryptBindEnvelope(perm.Value, enc)
	if err := inner.Decode(&bin.Buffer{Buf: pt[32:]}); err != nil {
		return inner, err
	}
	return inner, nil
}
