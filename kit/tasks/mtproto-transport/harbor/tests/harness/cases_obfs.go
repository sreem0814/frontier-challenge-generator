package main

import (
	"bytes"
	"encoding/binary"
	"fmt"
	"io"

	agobfs "github.com/gotd/td/mtproxy/obfuscated2"
	"github.com/gotd/td/mtproxy"
	refobfs "github.com/gotd/td/internal/zref/obfuscated2"
)

var obfsTags = [][4]byte{
	{0xef, 0xef, 0xef, 0xef},
	{0xee, 0xee, 0xee, 0xee},
	{0xdd, 0xdd, 0xdd, 0xdd},
}

var obfsDCs = []int{1, 2, 3, 4, 5, -2, -4, 203, 10004}

func obfsSecret(id string, i int) []byte {
	switch i % 4 {
	case 0:
		return nil
	case 1:
		return randBytes(rng(id, "secret"), 16)
	case 2:
		return randBytes(rng(id, "secret"), 17) // only the first 16 bytes count
	default:
		return randBytes(rng(id, "secret"), 32)
	}
}

// headerOK reports whether a 64-byte obfuscation header avoids the reserved
// starts listed in the transport documentation.
func headerOK(h []byte) bool {
	if len(h) != 64 || h[0] == 0xef {
		return false
	}
	switch binary.LittleEndian.Uint32(h[0:4]) {
	case 0x44414548, 0x54534f50, 0x20544547, 0x4954504f, 0x02010316, 0xdddddddd, 0xeeeeeeee:
		return false
	}
	return binary.LittleEndian.Uint32(h[4:8]) != 0
}

// badInit returns 64 bytes that must be rejected as an init header.
func badInit(src io.Reader, kind int) []byte {
	b := randBytes(src, 64)
	if b[0] == 0xef {
		b[0] = 0x01
	}
	if binary.LittleEndian.Uint32(b[4:8]) == 0 {
		b[4] = 1
	}
	switch kind % 9 {
	case 0:
		b[0] = 0xef
	case 1:
		copy(b, "HEAD")
	case 2:
		copy(b, "POST")
	case 3:
		copy(b, "GET ")
	case 4:
		copy(b, "OPTI")
	case 5:
		binary.LittleEndian.PutUint32(b, 0x02010316)
	case 6:
		binary.LittleEndian.PutUint32(b, 0xdddddddd)
	case 7:
		binary.LittleEndian.PutUint32(b, 0xeeeeeeee)
	default:
		binary.LittleEndian.PutUint32(b[4:8], 0)
	}
	return b
}

func registerObfs() {
	// Agent client against reference server.
	for i := 0; i < 24; i++ {
		id := fmt.Sprintf("obfs/client/%d", i)
		i := i
		add(id, func() string {
			tag := obfsTags[i%3]
			dc := obfsDCs[i%len(obfsDCs)]
			secret := obfsSecret(id, i)
			var src io.Reader = rng(id, "init")
			if i%6 == 5 {
				// Two rejected inits first; the client must draw again.
				s := rng(id, "bad")
				src = io.MultiReader(bytes.NewReader(badInit(s, i)), bytes.NewReader(badInit(s, i+4)), src)
			}
			cconn, sconn := newDuplex()
			cl := agobfs.NewObfuscated2(src, cconn)
			if err := cl.Handshake(tag, dc, mtproxy.Secret{Secret: secret}); err != nil {
				return "handshake err"
			}
			hdr := append([]byte(nil), cconn.out.Bytes()...)
			if len(hdr) != 64 {
				return fmt.Sprintf("header len %d", len(hdr))
			}
			hok := headerOK(hdr)
			payload := randBytes(rng(id, "c2s"), 64+i*97)
			orig := append([]byte(nil), payload...)
			if _, err := cl.Write(payload); err != nil {
				return "write err"
			}
			if !bytes.Equal(payload, orig) {
				return "input modified"
			}
			srw, md, err := refobfs.Accept(sconn, secret)
			if err != nil {
				return "accept err"
			}
			got := make([]byte, len(orig))
			if _, err := io.ReadFull(srw, got); err != nil {
				return "server read err"
			}
			reply := randBytes(rng(id, "s2c"), 32+i*61)
			if _, err := srw.Write(reply); err != nil {
				return "server write err"
			}
			back := make([]byte, len(reply))
			if _, err := io.ReadFull(chunkReaderRW{cl, 5 + i%11}, back); err != nil {
				return "client read err"
			}
			return join(
				fmt.Sprintf("hdr=%v", hok),
				hx(md.Protocol[:]), itoa(md.DC),
				fmt.Sprintf("c2s=%v", bytes.Equal(got, orig)),
				fmt.Sprintf("s2c=%v", bytes.Equal(back, reply)),
			)
		})
	}

	// Reference client against agent server.
	for i := 0; i < 24; i++ {
		id := fmt.Sprintf("obfs/server/%d", i)
		i := i
		add(id, func() string {
			tag := obfsTags[(i+1)%3]
			dc := obfsDCs[(i+3)%len(obfsDCs)]
			secret := obfsSecret(id, i+1)
			cconn, sconn := newDuplex()
			cl := refobfs.NewObfuscated2(rng(id, "init"), cconn)
			if err := cl.Handshake(tag, dc, mtproxy.Secret{Secret: secret}); err != nil {
				return "reference handshake err"
			}
			payload := randBytes(rng(id, "c2s"), 48+i*131)
			if _, err := cl.Write(append([]byte(nil), payload...)); err != nil {
				return "reference write err"
			}
			var conn io.ReadWriter = sconn
			if i%2 == 1 {
				conn = struct {
					io.Reader
					io.Writer
				}{chunkReader{sconn, 3 + i%13}, sconn}
			}
			srw, md, err := agobfs.Accept(conn, secret)
			if err != nil {
				return "accept err"
			}
			got := make([]byte, len(payload))
			if _, err := io.ReadFull(srw, got); err != nil {
				return "read err"
			}
			reply := randBytes(rng(id, "s2c"), 16+i*77)
			if _, err := srw.Write(reply); err != nil {
				return "write err"
			}
			back := make([]byte, len(reply))
			if _, err := io.ReadFull(cl, back); err != nil {
				return "reference read err"
			}
			return join(hx(md.Protocol[:]), itoa(md.DC),
				fmt.Sprintf("c2s=%v", bytes.Equal(got, payload)),
				fmt.Sprintf("s2c=%v", bytes.Equal(back, reply)))
		})
	}

	// A header sent with one secret, accepted with another (or none):
	// Accept does not fail but the metadata is garbage; the agent must decode
	// exactly what the reference derives.
	for i := 0; i < 6; i++ {
		id := fmt.Sprintf("obfs/wrongsecret/%d", i)
		i := i
		add(id, func() string {
			cconn, sconn := newDuplex()
			cl := refobfs.NewObfuscated2(rng(id, "init"), cconn)
			if err := cl.Handshake(obfsTags[i%3], 2, mtproxy.Secret{Secret: randBytes(rng(id, "s1"), 16)}); err != nil {
				return "reference handshake err"
			}
			var other []byte
			if i%2 == 0 {
				other = randBytes(rng(id, "s2"), 16)
			}
			_, md, err := agobfs.Accept(sconn, other)
			if err != nil {
				return "accept err"
			}
			return join(hx(md.Protocol[:]), itoa(md.DC))
		})
	}

	// Secrets of 1..15 bytes are rejected, on both sides; a valid one works.
	add("obfs/shortsecret", func() string {
		var res []string
		for _, n := range []int{16, 1, 8, 15} {
			cconn, _ := newDuplex()
			cl := agobfs.NewObfuscated2(rng("short", itoa(n)), cconn)
			err := cl.Handshake(obfsTags[0], 2, mtproxy.Secret{Secret: randBytes(rng("ss", itoa(n)), n)})
			res = append(res, errOr(err, "ok"))
		}
		for _, n := range []int{16, 3, 15} {
			cconn, sconn := newDuplex()
			ref := refobfs.NewObfuscated2(rng("short2", itoa(n)), cconn)
			if err := ref.Handshake(obfsTags[1], 2, mtproxy.Secret{}); err != nil {
				return "reference handshake err"
			}
			_, _, err := agobfs.Accept(sconn, randBytes(rng("ss2", itoa(n)), n))
			res = append(res, errOr(err, "ok"))
		}
		return join(res...)
	})

	// Accept on a truncated header fails; a full one succeeds.
	add("obfs/shortheader", func() string {
		cconn, sconn := newDuplex()
		ref := refobfs.NewObfuscated2(rng("shorthdr"), cconn)
		if err := ref.Handshake(obfsTags[2], 3, mtproxy.Secret{}); err != nil {
			return "reference handshake err"
		}
		full := append([]byte(nil), sconn.in.Bytes()...)
		_, md, err := agobfs.Accept(bytes.NewBuffer(full), nil)
		r1 := errOr(err, hx(md.Protocol[:])+itoa(md.DC))
		_, _, err = agobfs.Accept(bytes.NewBuffer(full[:40]), nil)
		return join(r1, errOr(err, "ok"))
	})

	// Long streams in both directions with many writes of odd sizes.
	for i := 0; i < 6; i++ {
		id := fmt.Sprintf("obfs/stream/%d", i)
		i := i
		add(id, func() string {
			cconn, sconn := newDuplex()
			cl := agobfs.NewObfuscated2(rng(id, "init"), cconn)
			secret := obfsSecret(id, i)
			if err := cl.Handshake(obfsTags[i%3], 1+i, mtproxy.Secret{Secret: secret}); err != nil {
				return "handshake err"
			}
			r := prng(id)
			var sent []byte
			for j := 0; j < 50; j++ {
				p := randBytes(rng(id, itoa(j)), 1+r.IntN(3000))
				sent = append(sent, p...)
				if _, err := cl.Write(p); err != nil {
					return "write err"
				}
			}
			srw, _, err := refobfs.Accept(sconn, secret)
			if err != nil {
				return "accept err"
			}
			got := make([]byte, len(sent))
			if _, err := io.ReadFull(chunkReader{srw, 1000}, got); err != nil {
				return "read err"
			}
			return fmt.Sprintf("%v:%s", bytes.Equal(got, sent), h8(sent))
		})
	}
}

// chunkReaderRW limits each Read of an io.Reader to n bytes.
type chunkReaderRW struct {
	r io.Reader
	n int
}

func (c chunkReaderRW) Read(p []byte) (int, error) {
	if len(p) > c.n {
		p = p[:c.n]
	}
	return c.r.Read(p)
}
