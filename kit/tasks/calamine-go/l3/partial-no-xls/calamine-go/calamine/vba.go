package calamine

// VBA project reader (port of calamine src/vba.rs and cfb.rs decompress_stream, after MS-OVBA).

import (
	"encoding/binary"
	"errors"
	"fmt"
	"sort"
	"strings"
)

// VbaReference is one project reference.
type VbaReference struct {
	Name, Description, Path string
}

// VbaModule is one module and its decoded source.
type VbaModule struct {
	Name, Source string
}

// VbaProject holds modules sorted by name and the references in dir-stream order.
type VbaProject struct {
	References []VbaReference
	Modules    []VbaModule
}

var power2 = [16]int{1, 1 << 1, 1 << 2, 1 << 3, 1 << 4, 1 << 5, 1 << 6, 1 << 7, 1 << 8, 1 << 9,
	1 << 10, 1 << 11, 1 << 12, 1 << 13, 1 << 14, 1 << 15}

// decompressStream is MS-OVBA 2.4.1 decompression exactly as calamine implements it.
func decompressStream(s []byte) ([]byte, error) {
	var res []byte
	if s[0] != 0x01 {
		return nil, errors.New("invalid signature")
	}
	i := 1
	for i < len(s) {
		header := u16(s[i:])
		i += 2
		start := len(res)
		chunkSize := int(header & 0x0FFF)
		sig := (header & 0x7000) >> 12
		flag := (header & 0x8000) >> 15
		if sig != 0b011 {
			panic("chunk signature")
		}
		if flag == 0 {
			res = append(res, s[i:i+4096]...)
			i += 4096
			continue
		}
		chunkLen := 0
	chunk:
		for {
			if i >= len(s) {
				break
			}
			bits := s[i]
			i++
			chunkLen++
			for b := 0; b < 8; b++ {
				if chunkLen > chunkSize {
					break chunk
				}
				if bits&(1<<b) == 0 {
					res = append(res, s[i])
					i++
					chunkLen++
				} else {
					token := u16(s[i:])
					i += 2
					chunkLen += 2
					dlen := len(res) - start
					bitCount := -1
					for k := 4; k < 16; k++ {
						if power2[k] >= dlen {
							bitCount = k
							break
						}
					}
					if bitCount < 0 {
						panic("copy token bit count")
					}
					lenMask := uint16(0xFFFF >> bitCount)
					n := int(token&lenMask) + 3
					offset := int((token&^lenMask)>>(16-bitCount)) + 1
					if offset > len(res) {
						panic("copy token offset")
					}
					for n > offset {
						chunkCopy := append([]byte(nil), res[len(res)-offset:]...)
						res = append(res, chunkCopy...)
						n -= offset
					}
					from := len(res) - offset
					res = append(res, res[from:from+n]...)
				}
			}
		}
	}
	return res, nil
}

type vbaStream struct{ b []byte }

func (s *vbaStream) skip(n int) { s.b = s.b[n:] }
func (s *vbaStream) readU16() (uint16, error) {
	if len(s.b) < 2 {
		return 0, errors.New("unexpected end of dir stream")
	}
	v := binary.LittleEndian.Uint16(s.b)
	s.b = s.b[2:]
	return v, nil
}
func (s *vbaStream) readU32() (uint32, error) {
	if len(s.b) < 4 {
		return 0, errors.New("unexpected end of dir stream")
	}
	v := binary.LittleEndian.Uint32(s.b)
	s.b = s.b[4:]
	return v, nil
}

func (s *vbaStream) variable(mult int) ([]byte, error) {
	n, err := s.readU32()
	if err != nil {
		return nil, err
	}
	l := int(n) * mult
	if l > len(s.b) {
		panic("variable record beyond stream")
	}
	out := s.b[:l]
	s.b = s.b[l:]
	return out, nil
}

func (s *vbaStream) check(id uint16) error {
	got, err := s.readU16()
	if err != nil {
		return err
	}
	if got != id {
		return fmt.Errorf("invalid record id: expecting %X found %X", id, got)
	}
	return nil
}

func (s *vbaStream) checkVariable(id uint16) ([]byte, error) {
	if id == 0x0047 && (len(s.b) < 2 || u16(s.b[:2]) != id) {
		return nil, nil
	}
	if err := s.check(id); err != nil {
		return nil, err
	}
	return s.variable(1)
}

func decodeAll(e *textEncoding, b []byte) string { return decodeWithBOM(e, b) }

func (r *VbaReference) setLibid(s *vbaStream, enc *textEncoding) error {
	libid, err := s.variable(1)
	if err != nil {
		return err
	}
	if len(libid) == 0 || strings.HasSuffix(string(libid), "##") {
		return nil
	}
	l := decodeAll(enc, libid)
	i := strings.LastIndexByte(l, '#')
	if i < 0 {
		return errors.New("unexpected libid format")
	}
	desc := l[i+1:]
	rest := l[:i]
	path := rest
	if j := strings.LastIndexByte(rest, '#'); j >= 0 {
		path = rest[j+1:]
	}
	r.Description = desc
	if path != "" && r.Path == "" {
		r.Path = path
	}
	return nil
}

func readReferences(s *vbaStream, enc *textEncoding) ([]VbaReference, error) {
	var refs []VbaReference
	cur := VbaReference{}
	for {
		id, err := s.readU16()
		if err != nil {
			return nil, err
		}
		switch id {
		case 0x000F:
			if cur.Name != "" {
				refs = append(refs, cur)
			}
			return refs, nil
		case 0x0016:
			if cur.Name != "" {
				refs = append(refs, cur)
			}
			nb, err := s.variable(1)
			if err != nil {
				return nil, err
			}
			name := decodeAll(enc, nb)
			cur = VbaReference{Name: name, Description: name}
			if _, err := s.checkVariable(0x003E); err != nil {
				return nil, err
			}
		case 0x0033:
			if err := cur.setLibid(s, enc); err != nil {
				return nil, err
			}
		case 0x002F:
			s.skip(4)
			if err := cur.setLibid(s, enc); err != nil {
				return nil, err
			}
			s.skip(6)
			t, err := s.readU16()
			if err != nil {
				return nil, err
			}
			switch t {
			case 0x0016:
				if _, err := s.variable(1); err != nil {
					return nil, err
				}
				if _, err := s.checkVariable(0x003E); err != nil {
					return nil, err
				}
				if err := s.check(0x0030); err != nil {
					return nil, err
				}
			case 0x0030:
			default:
				return nil, fmt.Errorf("unknown token in reference control '%X'", t)
			}
			s.skip(4)
			if err := cur.setLibid(s, enc); err != nil {
				return nil, err
			}
			s.skip(26)
		case 0x000D:
			s.skip(4)
			if err := cur.setLibid(s, enc); err != nil {
				return nil, err
			}
			s.skip(6)
		case 0x000E:
			s.skip(4)
			abs, err := s.variable(1)
			if err != nil {
				return nil, err
			}
			a := decodeAll(enc, abs)
			cur.Path = strings.TrimPrefix(a, "*\\C")
			if _, err := s.variable(1); err != nil {
				return nil, err
			}
			s.skip(6)
		default:
			return nil, fmt.Errorf("unknown check id '%X'", id)
		}
	}
}

type vbaModuleMeta struct {
	name, stream string
	offset       int
}

func readModules(s *vbaStream, enc *textEncoding) ([]vbaModuleMeta, error) {
	s.skip(4)
	n, err := s.readU16()
	if err != nil {
		return nil, err
	}
	s.skip(8)
	var mods []vbaModuleMeta
	for k := 0; k < int(n); k++ {
		nb, err := s.checkVariable(0x0019)
		if err != nil {
			return nil, err
		}
		name := decodeAll(enc, nb)
		if _, err := s.checkVariable(0x0047); err != nil {
			return nil, err
		}
		sb, err := s.checkVariable(0x001A)
		if err != nil {
			return nil, err
		}
		stream := decodeAll(enc, sb)
		for _, id := range []uint16{0x0032, 0x001C, 0x0048} {
			if _, err := s.checkVariable(id); err != nil {
				return nil, err
			}
		}
		if err := s.check(0x0031); err != nil {
			return nil, err
		}
		s.skip(4)
		off, err := s.readU32()
		if err != nil {
			return nil, err
		}
		if err := s.check(0x001E); err != nil {
			return nil, err
		}
		s.skip(8)
		if err := s.check(0x002C); err != nil {
			return nil, err
		}
		s.skip(6)
		t, err := s.readU16()
		if err != nil {
			return nil, err
		}
		if t != 0x0021 && t != 0x0022 {
			return nil, fmt.Errorf("unknown module typ '%X'", t)
		}
		for {
			s.skip(4)
			id, err := s.readU16()
			if err != nil {
				return nil, err
			}
			if id == 0x0025 || id == 0x0028 {
				continue
			}
			if id == 0x002B {
				break
			}
			return nil, fmt.Errorf("unknown record id '%X'", id)
		}
		s.skip(4)
		mods = append(mods, vbaModuleMeta{name, stream, int(off)})
	}
	return mods, nil
}

// readVbaProject parses a VBA project stored in c (its "dir" stream and module streams).
func readVbaProject(c *cfb, r *fileReader) (*VbaProject, error) {
	raw, err := c.getStream("dir", r)
	if err != nil {
		return nil, err
	}
	dir, err := decompressStream(raw)
	if err != nil {
		return nil, err
	}
	s := &vbaStream{b: dir}
	// dir information
	s.skip(10)
	if u16(s.b[0:2]) == 0x004A {
		s.skip(10)
	}
	s.skip(20)
	enc, err := encodingFromCodepage(u16(s.b[6:8]))
	if err != nil {
		return nil, err
	}
	s.skip(8)
	for _, id := range []uint16{0x0004, 0x0005, 0x0040, 0x0006, 0x003D} {
		if _, err := s.checkVariable(id); err != nil {
			return nil, err
		}
	}
	s.skip(32)
	for _, id := range []uint16{0x000C, 0x003C} {
		if _, err := s.checkVariable(id); err != nil {
			return nil, err
		}
	}
	refs, err := readReferences(s, enc)
	if err != nil {
		return nil, err
	}
	metas, err := readModules(s, enc)
	if err != nil {
		return nil, err
	}
	byName := map[string]string{}
	for _, m := range metas {
		st, err := c.getStream(m.stream, r)
		if err != nil {
			return nil, err
		}
		src, err := decompressStream(st[m.offset:])
		if err != nil {
			return nil, err
		}
		byName[m.name] = decodeAll(enc, src)
	}
	p := &VbaProject{References: refs}
	for n, src := range byName {
		p.Modules = append(p.Modules, VbaModule{n, src})
	}
	sort.Slice(p.Modules, func(i, j int) bool { return p.Modules[i].Name < p.Modules[j].Name })
	return p, nil
}

// vbaFromBin opens a standalone vbaProject.bin.
func vbaFromBin(b []byte) (p *VbaProject, err error) {
	r := &fileReader{buf: b}
	c, err := newCfb(r, len(b))
	if err != nil {
		return nil, err
	}
	return readVbaProject(c, r)
}
