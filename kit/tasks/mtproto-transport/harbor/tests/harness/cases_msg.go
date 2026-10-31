package main

import (
	"bytes"
	"crypto/aes"
	"crypto/sha1"
	"encoding/binary"
	"fmt"
	"io"

	"github.com/gotd/ige"

	"github.com/gotd/td/bin"
	agcrypto "github.com/gotd/td/crypto"
	refcrypto "github.com/gotd/td/internal/zref/crypto"
	"github.com/gotd/td/mt"
)

func randKey(src io.Reader) (k agcrypto.Key) {
	copy(k[:], randBytes(src, 256))
	return k
}

func refKey(k agcrypto.Key) refcrypto.AuthKey {
	return refcrypto.Key(k).WithID()
}

func agKey(k agcrypto.Key) agcrypto.AuthKey {
	// The ID is computed by the reference so that a broken Key.ID does not
	// hide the rest of the cipher.
	return agcrypto.AuthKey{Value: k, ID: refcrypto.Key(k).ID()}
}

func i128(src io.Reader) (v bin.Int128) {
	copy(v[:], randBytes(src, 16))
	return v
}

func i256(src io.Reader) (v bin.Int256) {
	copy(v[:], randBytes(src, 32))
	return v
}

func sides(i int) agcrypto.Side {
	if i%2 == 0 {
		return agcrypto.Client
	}
	return agcrypto.Server
}

// dataFields renders decoded message data deterministically.
func dataFields(d *agcrypto.EncryptedMessageData) string {
	if d == nil {
		return "nil"
	}
	n := int(d.MessageDataLen)
	if n < 0 || n > len(d.MessageDataWithPadding) {
		return "badlen"
	}
	return fmt.Sprintf("%d/%d/%d/%d/%d/%s", d.Salt, d.SessionID, d.MessageID, d.SeqNo, d.MessageDataLen,
		h8(d.MessageDataWithPadding[:n]))
}

func refDataFields(d *refcrypto.EncryptedMessageData) string {
	if d == nil {
		return "nil"
	}
	n := int(d.MessageDataLen)
	if n < 0 || n > len(d.MessageDataWithPadding) {
		return "badlen"
	}
	return fmt.Sprintf("%d/%d/%d/%d/%d/%s", d.Salt, d.SessionID, d.MessageID, d.SeqNo, d.MessageDataLen,
		h8(d.MessageDataWithPadding[:n]))
}

// rawEncrypt builds an MTProto 2.0 message from an explicit plaintext (header,
// data and padding chosen by the caller) using reference primitives.
func rawEncrypt(k refcrypto.Key, side refcrypto.Side, plaintext []byte) []byte {
	msgKey := refcrypto.MessageKey(k, plaintext, side)
	key, iv := refcrypto.Keys(k, msgKey, side)
	enc := make([]byte, len(plaintext))
	block, err := aes.NewCipher(key[:])
	if err != nil {
		panic(err)
	}
	ige.EncryptBlocks(block, iv[:], enc, plaintext)
	id := k.ID()
	out := append([]byte(nil), id[:]...)
	out = append(out, msgKey[:]...)
	return append(out, enc...)
}

func plainHeader(src io.Reader, dataLen int32) []byte {
	b := randBytes(src, 32)
	binary.LittleEndian.PutUint32(b[24:28], 0)
	binary.LittleEndian.PutUint32(b[28:32], uint32(dataLen))
	return b
}

func registerMsg() {
	// auth_key_id and aux_hash.
	for i := 0; i < 16; i++ {
		id := fmt.Sprintf("msg/keyid/%d", i)
		add(id, func() string {
			k := randKey(rng(id))
			kid := k.ID()
			aux := k.AuxHash()
			ak := k.WithID()
			return join(hx(kid[:]), hx(aux[:]), hx(ak.ID[:]))
		})
	}

	// MTProto 2.0 KDF.
	for i := 0; i < 24; i++ {
		id := fmt.Sprintf("msg/kdf2/%d", i)
		i := i
		add(id, func() string {
			src := rng(id)
			k := randKey(src)
			mk := i128(src)
			side := sides(i)
			key, iv := agcrypto.Keys(k, mk, side)
			pt := randBytes(src, 16*(2+i*3))
			m := agcrypto.MessageKey(k, pt, side)
			m2 := agcrypto.MessageKey(k, pt, side.DecryptSide())
			return join(hx(key[:]), hx(iv[:]), hx(m[:]), hx(m2[:]))
		})
	}

	// MTProto 1.0 KDF and the v1 helpers.
	for i := 0; i < 16; i++ {
		id := fmt.Sprintf("msg/kdf1/%d", i)
		i := i
		add(id, func() string {
			src := rng(id)
			k := randKey(src)
			mk := i128(src)
			key, iv := agcrypto.OldKeys(k, mk, sides(i))
			key1, iv1 := agcrypto.KeysV1(k, mk)
			m := agcrypto.MessageKeyV1(randBytes(src, 7+i*29))
			return join(hx(key[:]), hx(iv[:]), hx(key1[:]), hx(iv1[:]), hx(m[:]))
		})
	}

	// EncryptedMessage wire format.
	for i := 0; i < 8; i++ {
		id := fmt.Sprintf("msg/envelope/%d", i)
		i := i
		add(id, func() string {
			src := rng(id)
			var m agcrypto.EncryptedMessage
			copy(m.AuthKeyID[:], randBytes(src, 8))
			m.MsgKey = i128(src)
			m.EncryptedData = randBytes(src, 16*(1+i*5))
			b := new(bin.Buffer)
			enc := errOr(m.Encode(b), h8(b.Buf))
			raw := append([]byte(nil), b.Buf...)
			var d agcrypto.EncryptedMessage
			dec := errOr(d.Decode(&bin.Buffer{Buf: append([]byte(nil), raw...)}), hx(d.AuthKeyID[:])+hx(d.MsgKey[:])+h8(d.EncryptedData))
			var d2 agcrypto.EncryptedMessage
			dec2 := errOr(d2.DecodeWithoutCopy(&bin.Buffer{Buf: append([]byte(nil), raw...)}), hx(d2.AuthKeyID[:])+hx(d2.MsgKey[:])+h8(d2.EncryptedData))
			var d3 agcrypto.EncryptedMessage
			short := errOr(d3.Decode(&bin.Buffer{Buf: randBytes(src, 8+i)}), "ok")
			return join(enc, dec, dec2, short)
		})
	}

	// EncryptedMessageData wire format, with and without an inner encoder.
	for i := 0; i < 10; i++ {
		id := fmt.Sprintf("msg/data/%d", i)
		i := i
		add(id, func() string {
			src := rng(id)
			r := prng(id)
			d := agcrypto.EncryptedMessageData{
				Salt:      int64(r.Uint64()),
				SessionID: int64(r.Uint64()),
				MessageID: int64(r.Uint64()),
				SeqNo:     int32(r.Uint32()),
			}
			body := randBytes(src, 4*(1+i*7))
			pad := randBytes(src, 12+r.IntN(16))
			d.MessageDataLen = int32(len(body))
			d.MessageDataWithPadding = append(append([]byte(nil), body...), pad...)
			b := new(bin.Buffer)
			enc := errOr(d.Encode(b), h8(b.Buf))
			raw := append([]byte(nil), b.Buf...)

			// With Message set, MessageDataLen and MessageDataWithPadding are ignored.
			d2 := d
			d2.MessageDataLen = 9999
			d2.Message = &mt.PingRequest{PingID: int64(r.Uint64())}
			b2 := new(bin.Buffer)
			enc2 := errOr(d2.EncodeWithoutCopy(b2), h8(b2.Buf))

			var x agcrypto.EncryptedMessageData
			dec := errOr(x.Decode(&bin.Buffer{Buf: append([]byte(nil), raw...)}), dataFields(&x)+":"+h8(x.MessageDataWithPadding))
			data := "nil"
			if x.MessageDataLen == d.MessageDataLen && len(x.MessageDataWithPadding) >= len(body) {
				data = h8(x.Data())
			}
			var y agcrypto.EncryptedMessageData
			dec2 := errOr(y.DecodeWithoutCopy(&bin.Buffer{Buf: append([]byte(nil), raw...)}), dataFields(&y))

			bad := append([]byte(nil), raw[:32]...)
			binary.LittleEndian.PutUint32(bad[28:32], uint32(len(body)+len(pad)+4))
			bad = append(bad, body...)
			bad = append(bad, pad...)
			var z agcrypto.EncryptedMessageData
			tooLong := errOr(z.Decode(&bin.Buffer{Buf: bad}), "ok")
			var z2 agcrypto.EncryptedMessageData
			short := errOr(z2.Decode(&bin.Buffer{Buf: raw[:20]}), "ok")
			return join(enc, enc2, dec, data, dec2, tooLong, short)
		})
	}

	// Agent encrypts, reference decrypts (opposite side).
	for i := 0; i < 32; i++ {
		id := fmt.Sprintf("msg/encrypt/%d", i)
		i := i
		add(id, func() string {
			src := rng(id)
			r := prng(id)
			k := randKey(src)
			var c agcrypto.Cipher
			var rc refcrypto.Cipher
			if i%2 == 0 {
				c = agcrypto.NewClientCipher(rng(id, "pad"))
				rc = refcrypto.NewServerCipher(rng(id, "ref"))
			} else {
				c = agcrypto.NewServerCipher(rng(id, "pad"))
				rc = refcrypto.NewClientCipher(rng(id, "ref"))
			}
			d := agcrypto.EncryptedMessageData{
				Salt:      int64(r.Uint64()),
				SessionID: int64(r.Uint64()),
				MessageID: int64(r.Uint64()),
				SeqNo:     int32(r.IntN(1 << 20)),
			}
			if i%3 == 0 {
				d.Message = &mt.PingRequest{PingID: int64(r.Uint64())}
			} else {
				body := randBytes(src, 4*(1+r.IntN(400)))
				if i%7 == 0 {
					body = randBytes(src, 4*(20000+r.IntN(1000)))
				}
				d.MessageDataLen = int32(len(body))
				d.MessageDataWithPadding = body
			}
			b := &bin.Buffer{Buf: []byte("stale bytes that must be dropped")}
			if err := c.Encrypt(agKey(k), d, b); err != nil {
				return "encrypt err"
			}
			wire := append([]byte(nil), b.Buf...)
			if len(wire) < 24 {
				return "short"
			}
			got, err := rc.DecryptFromBuffer(refKey(k), &bin.Buffer{Buf: append([]byte(nil), wire...)})
			if err != nil {
				return "reference decrypt err"
			}
			total := len(wire) - 24
			pad := total - 32 - int(got.MessageDataLen)
			props := fmt.Sprintf("aligned=%v pad=%v", total%16 == 0, pad >= 12 && pad <= 1024)
			return join(refDataFields(got), props)
		})
	}

	// Reference encrypts, agent decrypts.
	for i := 0; i < 24; i++ {
		id := fmt.Sprintf("msg/decrypt/%d", i)
		i := i
		add(id, func() string {
			src := rng(id)
			r := prng(id)
			k := randKey(src)
			var rc refcrypto.Cipher
			var c agcrypto.Cipher
			if i%2 == 0 {
				rc = refcrypto.NewClientCipher(rng(id, "pad"))
				c = agcrypto.NewServerCipher(rng(id, "x"))
			} else {
				rc = refcrypto.NewServerCipher(rng(id, "pad"))
				c = agcrypto.NewClientCipher(rng(id, "x"))
			}
			body := randBytes(src, 4*(1+r.IntN(500)))
			d := refcrypto.EncryptedMessageData{
				Salt:                   int64(r.Uint64()),
				SessionID:              int64(r.Uint64()),
				MessageID:              int64(r.Uint64()),
				SeqNo:                  int32(r.IntN(1 << 20)),
				MessageDataLen:         int32(len(body)),
				MessageDataWithPadding: body,
			}
			b := new(bin.Buffer)
			if err := rc.Encrypt(refKey(k), d, b); err != nil {
				return "reference encrypt err"
			}
			wire := b.Buf
			var res []string
			got, err := c.DecryptFromBuffer(agKey(k), &bin.Buffer{Buf: append([]byte(nil), wire...)})
			res = append(res, errOr(err, dataFields(got)))
			var em agcrypto.EncryptedMessage
			copy(em.AuthKeyID[:], wire[:8])
			copy(em.MsgKey[:], wire[8:24])
			em.EncryptedData = append([]byte(nil), wire[24:]...)
			got2, err := c.Decrypt(agKey(k), &em)
			res = append(res, errOr(err, dataFields(got2)))
			return join(res...)
		})
	}

	// Decrypt must reject tampered or malformed messages, and accept the
	// well-formed control in the same case.
	type tamper struct {
		name string
		make func(k refcrypto.Key, src io.Reader) []byte
	}
	server := refcrypto.Server
	tampers := []tamper{
		{"wrongkeyid", func(k refcrypto.Key, src io.Reader) []byte {
			w := rawEncrypt(k, server, append(plainHeader(src, 16), randBytes(src, 16+16)...))
			w[3] ^= 0x80
			return w
		}},
		{"flipped", func(k refcrypto.Key, src io.Reader) []byte {
			w := rawEncrypt(k, server, append(plainHeader(src, 32), randBytes(src, 32+16)...))
			w[len(w)-20] ^= 0x01
			return w
		}},
		{"msgkey", func(k refcrypto.Key, src io.Reader) []byte {
			w := rawEncrypt(k, server, append(plainHeader(src, 16), randBytes(src, 16+16)...))
			w[10] ^= 0x01
			return w
		}},
		{"unaligned", func(k refcrypto.Key, src io.Reader) []byte {
			w := rawEncrypt(k, server, append(plainHeader(src, 16), randBytes(src, 16+16)...))
			return w[:len(w)-5]
		}},
		{"wrongside", func(k refcrypto.Key, src io.Reader) []byte {
			return rawEncrypt(k, refcrypto.Client, append(plainHeader(src, 16), randBytes(src, 16+16)...))
		}},
		{"lenodd", func(k refcrypto.Key, src io.Reader) []byte {
			return rawEncrypt(k, server, append(plainHeader(src, 18), randBytes(src, 48)...))
		}},
		{"lenneg", func(k refcrypto.Key, src io.Reader) []byte {
			return rawEncrypt(k, server, append(plainHeader(src, -16), randBytes(src, 48)...))
		}},
		{"lentoolong", func(k refcrypto.Key, src io.Reader) []byte {
			return rawEncrypt(k, server, append(plainHeader(src, 64), randBytes(src, 32)...))
		}},
		{"bigpadding", func(k refcrypto.Key, src io.Reader) []byte {
			return rawEncrypt(k, server, append(plainHeader(src, 16), randBytes(src, 16+1040)...))
		}},
		{"short", func(k refcrypto.Key, src io.Reader) []byte {
			w := rawEncrypt(k, server, append(plainHeader(src, 16), randBytes(src, 16+16)...))
			return w[:20]
		}},
	}
	for _, t := range tampers {
		for j := 0; j < 2; j++ {
			t, id := t, fmt.Sprintf("msg/reject/%s/%d", t.name, j)
			add(id, func() string {
				src := rng(id)
				k := refcrypto.Key(randKey(src))
				c := agcrypto.NewClientCipher(rng(id, "x"))
				// Control: a well-formed server message with 1024 bytes of
				// padding (the maximum) and 12 (the minimum).
				var res []string
				for _, padLen := range []int{1024, 12} {
					body := randBytes(src, 4*(1+j))
					pt := append(plainHeader(src, int32(len(body))), body...)
					extra := padLen - (len(pt)+padLen)%16 // at most 1024
					if padLen == 12 {
						extra = padLen + (16-(len(pt)+padLen)%16)%16 // at least 12
					}
					pt = append(pt, randBytes(src, extra)...)
					good := rawEncrypt(k, server, pt)
					got, err := c.DecryptFromBuffer(agKey(agcrypto.Key(k)), &bin.Buffer{Buf: good})
					res = append(res, errOr(err, dataFields(got)))
				}
				bad := t.make(k, src)
				_, err := c.DecryptFromBuffer(agKey(agcrypto.Key(k)), &bin.Buffer{Buf: bad})
				res = append(res, errOr(err, "accepted"))
				return join(res...)
			})
		}
	}

	// data_with_hash.
	for i := 0; i < 16; i++ {
		id := fmt.Sprintf("msg/datawithhash/%d", i)
		i := i
		add(id, func() string {
			src := rng(id)
			data := randBytes(src, i*13+1)
			dwh, err := agcrypto.DataWithHash(data, rng(id, "pad"))
			if err != nil {
				return "err"
			}
			h := sha1.Sum(data)
			props := fmt.Sprintf("%v/%v/%v/%v", len(dwh)%16 == 0, len(dwh)-20-len(data) < 16,
				bytes.Equal(dwh[:20], h[:]), bytes.Equal(dwh[20:20+len(data)], data))
			back := refcrypto.GuessDataWithHash(dwh)
			// Guess on reference-built inputs with 0..15 trailing bytes.
			var guesses []string
			for pad := 0; pad < 16; pad += 5 {
				in := append(append(append([]byte(nil), h[:]...), data...), randBytes(src, pad)...)
				g := agcrypto.GuessDataWithHash(in)
				if g == nil {
					guesses = append(guesses, "nil")
				} else {
					guesses = append(guesses, h8(g))
				}
			}
			nilShort := agcrypto.GuessDataWithHash(randBytes(src, 20)) == nil
			nilBad := agcrypto.GuessDataWithHash(randBytes(src, 64)) == nil
			return join(props, h8(back), join(guesses...), fmt.Sprintf("%v/%v", nilShort, nilBad))
		})
	}

	// bind_auth_key_inner and the MTProto 1.0 binding message.
	for i := 0; i < 12; i++ {
		id := fmt.Sprintf("msg/bind/%d", i)
		add(id, func() string {
			src := rng(id)
			r := prng(id)
			inner := &agcrypto.BindAuthKeyInner{
				Nonce:         int64(r.Uint64()),
				TempAuthKeyID: int64(r.Uint64()),
				PermAuthKeyID: int64(r.Uint64()),
				TempSessionID: int64(r.Uint64()),
				ExpiresAt:     int(r.Int32()),
			}
			b := new(bin.Buffer)
			enc := errOr(inner.Encode(b), hx(b.Buf))
			var dec agcrypto.BindAuthKeyInner
			refb := new(bin.Buffer)
			_ = (&refcrypto.BindAuthKeyInner{
				Nonce: inner.Nonce, TempAuthKeyID: inner.TempAuthKeyID, PermAuthKeyID: inner.PermAuthKeyID,
				TempSessionID: inner.TempSessionID, ExpiresAt: inner.ExpiresAt,
			}).Encode(refb)
			decRes := errOr(dec.Decode(&bin.Buffer{Buf: append([]byte(nil), refb.Buf...)}), fmt.Sprintf("%+v", dec))
			wrong := append([]byte(nil), refb.Buf...)
			wrong[0] ^= 0xff
			var dec2 agcrypto.BindAuthKeyInner
			wrongRes := errOr(dec2.Decode(&bin.Buffer{Buf: wrong}), "ok")
			var dec3 agcrypto.BindAuthKeyInner
			shortRes := errOr(dec3.Decode(&bin.Buffer{Buf: refb.Buf[:20]}), "ok")

			perm := randKey(src)
			msgID := int64(r.Uint64())
			out, err := agcrypto.EncryptBindMessage(rng(id, "bind"), agKey(perm), msgID, inner)
			bindRes := "err"
			if err == nil {
				bindRes = checkBind(refcrypto.Key(perm), msgID, refb.Buf, out)
			}
			_, zerr := agcrypto.EncryptBindMessage(rng(id, "z"), agcrypto.AuthKey{}, msgID, inner)
			return join(enc, decRes, wrongRes, shortRes, bindRes, errOr(zerr, "ok"))
		})
	}
}

// checkBind decrypts a binding message with the reference v1 KDF and
// verifies its envelope.
func checkBind(perm refcrypto.Key, msgID int64, innerEnc, out []byte) string {
	if len(out) < 24 || (len(out)-24)%16 != 0 {
		return "badlen"
	}
	id := perm.ID()
	if !bytes.Equal(out[:8], id[:]) {
		return "badkeyid"
	}
	var mk bin.Int128
	copy(mk[:], out[8:24])
	key, iv := refcrypto.KeysV1(perm, mk)
	pt := make([]byte, len(out)-24)
	ige.DecryptAES256Blocks(key[:], iv[:], pt, out[24:])
	if len(pt) < 32+len(innerEnc) {
		return "short"
	}
	env := pt[:32+len(innerEnc)]
	if refcrypto.MessageKeyV1(env) != mk {
		return "badmsgkey"
	}
	if int64(binary.LittleEndian.Uint64(pt[16:24])) != msgID {
		return "badmsgid"
	}
	if binary.LittleEndian.Uint32(pt[24:28]) != 0 {
		return "badseq"
	}
	if int(binary.LittleEndian.Uint32(pt[28:32])) != len(innerEnc) {
		return "badmsglen"
	}
	if !bytes.Equal(pt[32:32+len(innerEnc)], innerEnc) {
		return "badinner"
	}
	if len(pt)-len(env) >= 16 {
		return "badpad"
	}
	return "ok"
}
