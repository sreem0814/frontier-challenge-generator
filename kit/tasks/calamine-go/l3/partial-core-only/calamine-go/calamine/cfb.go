package calamine

// Compound File Binary (MS-CFB) reader and the xls string decoding helpers
// (port of calamine src/cfb.rs).

import (
	"encoding/binary"
	"errors"
	"fmt"
	"strings"
	"unicode/utf8"

	"golang.org/x/text/encoding"
	"golang.org/x/text/encoding/htmlindex"
)

const (
	reservedSectors = 0xFFFF_FFFA
	difSect         = 0xFFFF_FFFC
	endOfChain      = 0xFFFF_FFFE
)

var errSectorBeyondEOF = errors.New("cfb: sector beyond end of file")

// fileReader is a sequential reader over the whole file, shared by the main
// sectors and the mini sectors exactly like the Rust reader is.
type fileReader struct {
	buf []byte
	pos int
}

func (r *fileReader) read(p []byte) int {
	n := copy(p, r.buf[r.pos:])
	r.pos += n
	return n
}

type sectors struct {
	data  []byte
	size  int
	maxid uint32
}

func (s *sectors) get(id uint32, r *fileReader) ([]byte, error) {
	if s.maxid < id {
		return nil, errSectorBeyondEOF
	}
	start := int(id) * s.size
	end := start + s.size
	if end > len(s.data) {
		l := len(s.data)
		if cap(s.data) >= end {
			s.data = s.data[:end]
			for i := l; i < end; i++ {
				s.data[i] = 0
			}
		} else {
			nd := make([]byte, end, end+end/2)
			copy(nd, s.data)
			s.data = nd
		}
		for l < end {
			n := r.read(s.data[l:end])
			if n == 0 {
				if start > l {
					return nil, errors.New("cfb: truncated sector")
				}
				return s.data[start:l], nil
			}
			l += n
		}
	}
	return s.data[start:end], nil
}

func (s *sectors) getChain(id uint32, fats []uint32, r *fileReader, length int) ([]byte, error) {
	var chain []byte
	guard := 0
	for id != endOfChain {
		sec, err := s.get(id, r)
		if err != nil {
			return nil, err
		}
		remaining := length - len(chain)
		toCopy := len(sec)
		if remaining < toCopy {
			toCopy = remaining
		}
		chain = append(chain, sec[:toCopy]...)
		if len(chain) >= length {
			break
		}
		if int(id) >= len(fats) {
			return nil, errors.New("cfb: fat index out of range")
		}
		id = fats[id]
		guard++
		if guard > 1<<26 {
			return nil, errors.New("cfb: sector chain loop")
		}
	}
	return chain, nil
}

type directory struct {
	name  string
	start uint32
	len   int
}

type cfb struct {
	dirs        []directory
	sectors     sectors
	fats        []uint32
	miniSectors sectors
	miniFats    []uint32
}

func toU32(b []byte) ([]uint32, error) {
	if len(b)%4 != 0 {
		return nil, errors.New("cfb: unaligned u32 table")
	}
	out := make([]uint32, len(b)/4)
	for i := range out {
		out[i] = binary.LittleEndian.Uint32(b[4*i:])
	}
	return out, nil
}

var oleSignature = []byte{0xD0, 0xCF, 0x11, 0xE0, 0xA1, 0xB1, 0x1A, 0xE1}

func newCfb(r *fileReader, length int) (*cfb, error) {
	var hdr [512]byte
	n := r.read(hdr[:])
	if n < 512 || string(hdr[:8]) != string(oleSignature) {
		return nil, errors.New("cfb: invalid OLE signature")
	}
	version := binary.LittleEndian.Uint16(hdr[26:])
	sectorSize := 0
	switch binary.LittleEndian.Uint16(hdr[30:]) {
	case 0x0009:
		sectorSize = 512
	case 0x000C:
		var rest [4096 - 512]byte
		if r.read(rest[:]) < len(rest) {
			return nil, errors.New("cfb: truncated header")
		}
		sectorSize = 4096
	default:
		return nil, errors.New("cfb: invalid sector shift")
	}
	if binary.LittleEndian.Uint16(hdr[32:]) != 0x0006 {
		return nil, errors.New("cfb: invalid minisector shift")
	}
	dirStart := binary.LittleEndian.Uint32(hdr[48:])
	miniFatStart := binary.LittleEndian.Uint32(hdr[60:])
	miniFatLen := int(binary.LittleEndian.Uint32(hdr[64:]))
	difatStart := binary.LittleEndian.Uint32(hdr[68:])
	difat, _ := toU32(hdr[76:512])

	maxid := length / sectorSize
	secs := sectors{size: sectorSize, maxid: uint32(maxid)}

	id := difatStart
	for id < reservedSectors {
		b, err := secs.get(id, r)
		if err != nil {
			return nil, err
		}
		v, err := toU32(b)
		if err != nil {
			return nil, err
		}
		difat = append(difat, v...)
		id = difat[len(difat)-1]
		difat = difat[:len(difat)-1]
	}
	var fats []uint32
	for _, fid := range difat {
		if fid >= difSect {
			continue
		}
		b, err := secs.get(fid, r)
		if err != nil {
			return nil, err
		}
		v, err := toU32(b)
		if err != nil {
			return nil, err
		}
		fats = append(fats, v...)
	}
	dirBytes, err := secs.getChain(dirStart, fats, r, int(^uint(0)>>1))
	if err != nil {
		return nil, err
	}
	var dirs []directory
	for i := 0; i < len(dirBytes); i += 128 {
		end := i + 128
		if end > len(dirBytes) {
			end = len(dirBytes)
		}
		c := dirBytes[i:end]
		if len(c) < 128 && (len(c) < 124 || sectorSize == 4096) {
			return nil, errors.New("cfb: short directory entry")
		}
		name := decodeWithBOM(encUTF16LE, c[:64])
		if k := strings.IndexByte(name, 0); k >= 0 {
			name = name[:k]
		}
		d := directory{name: name, start: binary.LittleEndian.Uint32(c[116:])}
		if sectorSize == 512 {
			d.len = int(binary.LittleEndian.Uint32(c[120:]))
		} else {
			d.len = int(binary.LittleEndian.Uint64(c[120:]))
		}
		dirs = append(dirs, d)
	}
	if len(dirs) == 0 || (version != 3 && dirs[0].start == endOfChain) {
		return nil, errors.New("cfb: empty root directory")
	}
	var miniFats []uint32
	var ministream []byte
	if miniFatLen > 0 {
		ministream, err = secs.getChain(dirs[0].start, fats, r, dirs[0].len)
		if err != nil {
			return nil, err
		}
		mf, err := secs.getChain(miniFatStart, fats, r, miniFatLen*sectorSize)
		if err != nil {
			return nil, err
		}
		miniFats, err = toU32(mf)
		if err != nil {
			return nil, err
		}
	}
	return &cfb{
		dirs:        dirs,
		sectors:     secs,
		fats:        fats,
		miniSectors: sectors{size: 64, data: ministream, maxid: uint32(maxid * 8)},
		miniFats:    miniFats,
	}, nil
}

func (c *cfb) hasDirectory(name string) bool {
	for _, d := range c.dirs {
		if d.name == name {
			return true
		}
	}
	return false
}

var errStreamNotFound = errors.New("cfb: stream not found")

func (c *cfb) getStream(name string, r *fileReader) ([]byte, error) {
	for _, d := range c.dirs {
		if d.name == name {
			if d.len < 4096 {
				return c.miniSectors.getChain(d.start, c.miniFats, r, d.len)
			}
			return c.sectors.getChain(d.start, c.fats, r, d.len)
		}
	}
	return nil, errStreamNotFound
}

// ---- text encodings (encoding_rs semantics through x/text) ----

type textEncoding struct {
	label      string
	enc        encoding.Encoding
	singleByte bool
	utf8       bool
	utf16le    bool
	utf16be    bool
}

var encUTF16LE = mustEnc("utf-16le")
var encUTF8 = mustEnc("utf-8")

func mustEnc(label string) *textEncoding {
	e, err := lookupEncoding(label)
	if err != nil {
		panic(err)
	}
	return e
}

var singleByteLabels = map[string]bool{
	"ibm866": true, "iso-8859-2": true, "iso-8859-3": true, "iso-8859-4": true, "iso-8859-5": true,
	"iso-8859-6": true, "iso-8859-7": true, "iso-8859-8": true, "iso-8859-8-i": true, "iso-8859-10": true,
	"iso-8859-13": true, "iso-8859-14": true, "iso-8859-15": true, "iso-8859-16": true, "koi8-r": true,
	"koi8-u": true, "macintosh": true, "windows-874": true, "windows-1250": true, "windows-1251": true,
	"windows-1252": true, "windows-1253": true, "windows-1254": true, "windows-1255": true,
	"windows-1256": true, "windows-1257": true, "windows-1258": true, "x-mac-cyrillic": true,
}

var encCache = map[string]*textEncoding{}

func lookupEncoding(label string) (*textEncoding, error) {
	if e, ok := encCache[label]; ok {
		return e, nil
	}
	te := &textEncoding{label: label}
	switch label {
	case "utf-8":
		te.utf8 = true
	case "utf-16le":
		te.utf16le = true
	case "utf-16be":
		te.utf16be = true
	case "replacement":
	default:
		l := label
		if l == "gbk" {
			l = "gb18030" // the WHATWG gbk decoder is the gb18030 decoder
		}
		e, err := htmlindex.Get(l)
		if err != nil {
			return nil, err
		}
		te.enc = e
	}
	te.singleByte = singleByteLabels[label]
	encCache[label] = te
	return te, nil
}

// codepageLabel maps Windows code pages to WHATWG encodings (the `codepage` crate's table).
var codepageLabel = map[uint16]string{
	65001: "utf-8", 1200: "utf-16le", 1252: "windows-1252", 1251: "windows-1251", 936: "gbk",
	932: "shift_jis", 949: "euc-kr", 1250: "windows-1250", 1256: "windows-1256", 1254: "windows-1254",
	950: "big5", 874: "windows-874", 1255: "windows-1255", 1253: "windows-1253", 1257: "windows-1257",
	1258: "windows-1258", 20932: "euc-jp", 28592: "iso-8859-2", 28605: "iso-8859-15",
	28597: "iso-8859-7", 20866: "koi8-r", 54936: "gb18030", 28595: "iso-8859-5", 38598: "iso-8859-8-i",
	28594: "iso-8859-4", 28596: "iso-8859-6", 50221: "iso-2022-jp", 21866: "koi8-u",
	28603: "iso-8859-13", 28593: "iso-8859-3", 1201: "utf-16be", 866: "ibm866", 28600: "iso-8859-10",
	28598: "iso-8859-8", 10000: "macintosh", 10017: "x-mac-cyrillic", 28604: "iso-8859-14",
	28606: "iso-8859-16", 951: "big5", 10007: "x-mac-cyrillic", 20936: "gbk", 20949: "euc-kr",
	21010: "utf-16le", 28591: "windows-1252", 28599: "windows-1254", 28601: "windows-874",
	50220: "iso-2022-jp", 50222: "iso-2022-jp", 50225: "replacement", 50227: "replacement",
	51936: "gbk", 51949: "euc-kr", 52936: "replacement",
}

func encodingFromCodepage(cp uint16) (*textEncoding, error) {
	l, ok := codepageLabel[cp]
	if !ok {
		return nil, fmt.Errorf("codepage %X not found", cp)
	}
	return lookupEncoding(l)
}

func decodeUTF16(b []byte, little bool) string {
	var sb strings.Builder
	sb.Grow(len(b))
	i := 0
	for ; i+1 < len(b); i += 2 {
		var u uint16
		if little {
			u = uint16(b[i]) | uint16(b[i+1])<<8
		} else {
			u = uint16(b[i+1]) | uint16(b[i])<<8
		}
		if u >= 0xD800 && u < 0xDC00 {
			if i+3 < len(b) {
				var u2 uint16
				if little {
					u2 = uint16(b[i+2]) | uint16(b[i+3])<<8
				} else {
					u2 = uint16(b[i+3]) | uint16(b[i+2])<<8
				}
				if u2 >= 0xDC00 && u2 < 0xE000 {
					sb.WriteRune(0x10000 + (rune(u)-0xD800)<<10 + (rune(u2) - 0xDC00))
					i += 2
					continue
				}
			}
			sb.WriteRune(utf8.RuneError)
			continue
		}
		if u >= 0xDC00 && u < 0xE000 {
			sb.WriteRune(utf8.RuneError)
			continue
		}
		sb.WriteRune(rune(u))
	}
	if i < len(b) {
		sb.WriteRune(utf8.RuneError)
	}
	return sb.String()
}

func decodeUTF8Lossy(b []byte) string {
	if utf8.Valid(b) {
		return string(b)
	}
	return strings.ToValidUTF8(string(b), "�")
}

// decodeNoBOM decodes without BOM sniffing.
func (e *textEncoding) decodeNoBOM(b []byte) string {
	switch {
	case e.utf8:
		return decodeUTF8Lossy(b)
	case e.utf16le:
		return decodeUTF16(b, true)
	case e.utf16be:
		return decodeUTF16(b, false)
	case e.enc == nil: // replacement
		if len(b) == 0 {
			return ""
		}
		return "�"
	}
	out, err := e.enc.NewDecoder().Bytes(b)
	if err != nil {
		return decodeUTF8Lossy(b)
	}
	return string(out)
}

// decodeWithBOM mirrors encoding_rs Encoding::decode: a leading BOM selects the encoding and is removed.
func decodeWithBOM(e *textEncoding, b []byte) string {
	switch {
	case len(b) >= 3 && b[0] == 0xEF && b[1] == 0xBB && b[2] == 0xBF:
		return decodeUTF8Lossy(b[3:])
	case len(b) >= 2 && b[0] == 0xFF && b[1] == 0xFE:
		return decodeUTF16(b[2:], true)
	case len(b) >= 2 && b[0] == 0xFE && b[1] == 0xFF:
		return decodeUTF16(b[2:], false)
	}
	return e.decodeNoBOM(b)
}

// xlsEncoding is calamine's XlsEncoding.
type xlsEncoding struct{ e *textEncoding }

// highByte: 0 = None, 1 = Some(false), 2 = Some(true)
const (
	hbNone = iota
	hbFalse
	hbTrue
)

func (x xlsEncoding) resolveHigh(hb int) int {
	if hb != hbNone {
		return hb
	}
	if x.e.utf8 || x.e.singleByte {
		return hbNone
	}
	return hbFalse
}

// decodeTo appends up to n characters from stream; returns (chars, bytes) consumed.
func (x xlsEncoding) decodeTo(stream []byte, n int, sb *strings.Builder, hb int) (int, int) {
	var l, ub int
	var bytes []byte
	switch x.resolveHigh(hb) {
	case hbNone:
		l = min(len(stream), n)
		ub = l
		bytes = stream[:l]
	case hbFalse:
		l = min(len(stream), n)
		ub = l
		bytes = make([]byte, 2*l)
		for i := 0; i < l; i++ {
			bytes[2*i] = stream[i]
		}
	default:
		l = min(len(stream)/2, n)
		ub = 2 * l
		bytes = stream[:2*l]
	}
	sb.WriteString(decodeWithBOM(x.e, bytes))
	return l, ub
}
