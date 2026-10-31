package main

import (
	"bytes"
	"errors"
	"fmt"
	"hash/crc32"
	"io"
	"testing/iotest"

	"github.com/gotd/td/bin"
	agcodec "github.com/gotd/td/proto/codec"
)

type ckind int

const (
	kAbridged ckind = iota
	kIntermediate
	kPadded
	kFull
)

var ckinds = []ckind{kAbridged, kIntermediate, kPadded, kFull}

func (k ckind) String() string {
	return [...]string{"abridged", "intermediate", "padded", "full"}[k]
}

func agentCodec(k ckind) agcodec.Codec {
	switch k {
	case kAbridged:
		return agcodec.Abridged{}
	case kIntermediate:
		return agcodec.Intermediate{}
	case kPadded:
		return agcodec.PaddedIntermediate{}
	default:
		return &agcodec.Full{}
	}
}

// frame builds one frame of kind k for payload p; seq is used by Full, pad by
// PaddedIntermediate.
func frame(k ckind, p []byte, seq int, pad []byte) []byte {
	var out []byte
	switch k {
	case kAbridged:
		n := len(p) / 4
		if n < 127 {
			out = append(out, byte(n))
		} else {
			out = append(out, 0x7f, byte(n), byte(n>>8), byte(n>>16))
		}
		out = append(out, p...)
	case kIntermediate:
		out = append(le32(uint32(len(p))), p...)
	case kPadded:
		out = append(le32(uint32(len(p)+len(pad))), p...)
		out = append(out, pad...)
	case kFull:
		out = append(le32(uint32(12+len(p))), le32(uint32(seq))...)
		out = append(out, p...)
		out = append(out, le32(crc32.ChecksumIEEE(out))...)
	}
	return out
}

func aligned(k ckind) bool { return k != kFull }

// payloadLens returns deterministic payload lengths for write/read cases.
func payloadLens(id string, k ckind, n int) []int {
	r := prng(id)
	// No 4-byte payloads: on read they are transport error codes.
	base := []int{8, 12, 16, 64, 500, 504, 508, 512, 1024, 4096, 65536}
	var out []int
	for i := 0; i < n; i++ {
		var l int
		if i < len(base) && r.IntN(3) == 0 {
			l = base[r.IntN(len(base))]
		} else {
			switch r.IntN(4) {
			case 0:
				l = 8 + r.IntN(200)
			case 1:
				l = 400 + r.IntN(300)
			case 2:
				l = 1000 + r.IntN(20000)
			default:
				l = 8 + r.IntN(2000)
			}
		}
		if aligned(k) {
			l = (l + 3) &^ 3
		}
		out = append(out, l)
	}
	return out
}

func readFrames(k ckind, r io.Reader, n int, junk bool) string {
	c := agentCodec(k)
	var res []string
	for i := 0; i < n; i++ {
		b := new(bin.Buffer)
		if junk {
			b.Buf = append(b.Buf, []byte("left over bytes from a previous message")...)
		}
		if err := c.Read(r, b); err != nil {
			res = append(res, "err")
			continue
		}
		res = append(res, h8(b.Buf))
	}
	return join(res...)
}

func protoCode(err error) string {
	var pe *agcodec.ProtocolErr
	if errors.As(err, &pe) {
		return fmt.Sprintf("proto:%d", pe.Code)
	}
	if err == nil {
		return "nil"
	}
	return "err"
}

func registerCodec() {
	// Protocol tags.
	for _, k := range ckinds {
		k := k
		add("codec/header/"+k.String(), func() string {
			c := agentCodec(k)
			var w bytes.Buffer
			werr := c.WriteHeader(&w)
			var tag string
			if t, ok := c.(agcodec.TaggedCodec); ok {
				ot := t.ObfuscatedTag()
				tag = hx(ot[:])
			}
			good := w.Bytes()
			rerr := c.ReadHeader(bytes.NewReader(append(append([]byte(nil), good...), 1, 2, 3, 4)))
			var bad []byte
			switch k {
			case kAbridged:
				bad = []byte{0xee}
			case kIntermediate:
				bad = []byte{0xdd, 0xdd, 0xdd, 0xdd}
			case kPadded:
				bad = []byte{0xee, 0xee, 0xee, 0xee}
			default:
				bad = nil
			}
			badRes := "skip"
			if bad != nil {
				err := c.ReadHeader(bytes.NewReader(bad))
				switch {
				case errors.Is(err, agcodec.ErrProtocolHeaderMismatch):
					badRes = "mismatch"
				case err == nil:
					badRes = "nil"
				default:
					badRes = "err"
				}
			}
			return join(errOr(werr, hx(good)), tag, errOr(rerr, "ok"), badRes)
		})
	}

	// Writes of deterministic frames, several per codec value.
	for _, k := range ckinds {
		for i := 0; i < 12; i++ {
			k, id := k, fmt.Sprintf("codec/write/%s/%d", k, i)
			add(id, func() string {
				lens := payloadLens(id, k, 1+i%4)
				src := rng(id)
				c := agentCodec(k)
				var w bytes.Buffer
				var payloads [][]byte
				for _, l := range lens {
					p := randBytes(src, l)
					payloads = append(payloads, p)
					b := &bin.Buffer{Buf: append([]byte(nil), p...)}
					if err := c.Write(&w, b); err != nil {
						return "err"
					}
				}
				if k != kPadded {
					return h8(w.Bytes())
				}
				// Padded: check each frame against its payload.
				r := bytes.NewReader(w.Bytes())
				var all []byte
				for _, p := range payloads {
					var lb [4]byte
					if _, err := io.ReadFull(r, lb[:]); err != nil {
						return "short"
					}
					n := int(lb[0]) | int(lb[1])<<8 | int(lb[2])<<16 | int(lb[3])<<24
					pad := n - len(p)
					if pad < 0 || pad > 3 {
						return "badpad"
					}
					body := make([]byte, n)
					if _, err := io.ReadFull(r, body); err != nil {
						return "short"
					}
					if !bytes.Equal(body[:len(p)], p) {
						return "badbody"
					}
					all = append(all, p...)
				}
				if r.Len() != 0 {
					return "trailing"
				}
				return "ok:" + h8(all)
			})
		}
	}

	// Write limits: empty, unaligned, oversize, exactly the maximum.
	for _, k := range ckinds {
		k := k
		add("codec/writelimits/"+k.String(), func() string {
			try := func(p []byte) string {
				c := agentCodec(k)
				var w bytes.Buffer
				err := c.Write(&w, &bin.Buffer{Buf: p})
				if err != nil {
					if w.Len() != 0 {
						return "err+written"
					}
					return "err"
				}
				if k == kPadded {
					return fmt.Sprintf("ok%v", w.Len()-len(p)-4 >= 0 && w.Len()-len(p)-4 <= 3)
				}
				return h8(w.Bytes())
			}
			src := rng("limits", k.String())
			return join(
				try(randBytes(src, 16)),
				try(nil),
				try(randBytes(src, 6)),
				try(randBytes(src, 1<<24+4)),
				try(randBytes(src, 1<<24)),
			)
		})
	}

	// Reads of well-formed streams, whole and byte by byte, with a dirty buffer.
	for _, k := range ckinds {
		for i := 0; i < 12; i++ {
			k, id := k, fmt.Sprintf("codec/read/%s/%d", k, i)
			add(id, func() string {
				lens := payloadLens(id, k, 1+i%5)
				src := rng(id)
				var stream []byte
				for j, l := range lens {
					p := randBytes(src, l)
					var pad []byte
					if k == kPadded {
						pad = randBytes(src, int(randBytes(src, 1)[0])%4)
					}
					stream = append(stream, frame(k, p, j, pad)...)
				}
				var r io.Reader = bytes.NewReader(stream)
				switch i % 3 {
				case 1:
					r = iotest.OneByteReader(r)
				case 2:
					r = chunkReader{r: r, n: 7}
				}
				return readFrames(k, r, len(lens), i%2 == 0)
			})
		}
	}

	// Transport errors: a 4-byte payload is a negated error code; the stream
	// stays usable afterwards.
	for _, k := range ckinds {
		k := k
		add("codec/protoerr/"+k.String(), func() string {
			src := rng("protoerr", k.String())
			codes := []int32{404, 429, 444, 1, 7}
			var stream []byte
			seq := 0
			for _, code := range codes {
				stream = append(stream, frame(k, le32(uint32(-code)), seq, nil)...)
				seq++
			}
			p := randBytes(src, 64)
			stream = append(stream, frame(k, p, seq, nil)...)
			c := agentCodec(k)
			r := bytes.NewReader(stream)
			var res []string
			for range codes {
				b := new(bin.Buffer)
				res = append(res, protoCode(c.Read(r, b)))
			}
			b := new(bin.Buffer)
			res = append(res, errOr(c.Read(r, b), h8(b.Buf)))
			return join(res...)
		})
	}

	// Malformed frames: each after a good frame on the same codec value.
	type bad struct {
		name  string
		kinds []ckind
		build func(k ckind, src io.Reader) []byte
	}
	bads := []bad{
		{"zerolen", []ckind{kIntermediate, kPadded, kFull}, func(k ckind, src io.Reader) []byte {
			return le32(0)
		}},
		{"hugelen", []ckind{kIntermediate, kPadded, kFull}, func(k ckind, src io.Reader) []byte {
			return append(le32(1<<24+16), randBytes(src, 64)...)
		}},
		{"neglen", []ckind{kIntermediate, kPadded, kFull}, func(k ckind, src io.Reader) []byte {
			return append(le32(0xfffffff0), randBytes(src, 64)...)
		}},
		{"truncated", ckinds, func(k ckind, src io.Reader) []byte {
			f := frame(k, randBytes(src, 400), 1, nil)
			return f[:len(f)-37]
		}},
		{"truncatedlen", []ckind{kAbridged}, func(k ckind, src io.Reader) []byte {
			return []byte{0x7f, 0x10}
		}},
		{"badcrc", []ckind{kFull}, func(k ckind, src io.Reader) []byte {
			f := frame(k, randBytes(src, 120), 1, nil)
			f[len(f)-1] ^= 0x55
			return f
		}},
		{"badbody", []ckind{kFull}, func(k ckind, src io.Reader) []byte {
			f := frame(k, randBytes(src, 120), 1, nil)
			f[20] ^= 0x01
			return f
		}},
		{"badseq", []ckind{kFull}, func(k ckind, src io.Reader) []byte {
			return frame(k, randBytes(src, 120), 7, nil)
		}},
		{"repeatseq", []ckind{kFull}, func(k ckind, src io.Reader) []byte {
			return frame(k, randBytes(src, 120), 0, nil)
		}},
	}
	for _, bd := range bads {
		for _, k := range bd.kinds {
			bd, k := bd, k
			add(fmt.Sprintf("codec/malformed/%s/%s", bd.name, k), func() string {
				src := rng("malformed", bd.name, k.String())
				p := randBytes(src, 96)
				stream := append(frame(k, p, 0, nil), bd.build(k, src)...)
				c := agentCodec(k)
				r := bytes.NewReader(stream)
				b1 := new(bin.Buffer)
				first := errOr(c.Read(r, b1), h8(b1.Buf))
				b2 := new(bin.Buffer)
				err := c.Read(r, b2)
				second := "err"
				if err == nil {
					second = "accepted"
				} else {
					var pe *agcodec.ProtocolErr
					if errors.As(err, &pe) {
						second = "proto"
					}
				}
				return join(first, second)
			})
		}
	}

	// Round trip through the agent's own writer and reader, many sizes.
	for _, k := range ckinds {
		k := k
		add("codec/roundtrip/"+k.String(), func() string {
			src := rng("roundtrip", k.String())
			r := prng("roundtrip", k.String())
			wc, rc := agentCodec(k), agentCodec(k)
			var w bytes.Buffer
			var want []byte
			for i := 0; i < 60; i++ {
				l := 4 * (2 + r.IntN(300))
				if i%10 == 9 {
					l = 4 * (100000 + r.IntN(50000))
				}
				p := randBytes(src, l)
				want = append(want, p...)
				if err := wc.Write(&w, &bin.Buffer{Buf: append([]byte(nil), p...)}); err != nil {
					return "err"
				}
			}
			var got []byte
			for i := 0; i < 60; i++ {
				b := new(bin.Buffer)
				if err := rc.Read(&w, b); err != nil {
					return fmt.Sprintf("readerr@%d", i)
				}
				got = append(got, b.Buf...)
			}
			if !bytes.Equal(got, want) {
				return "mismatch"
			}
			return "ok:" + h8(want)
		})
	}
}
