package calamine

// BIFF12 .xlsb reader (port of calamine src/xlsb/mod.rs and cells_reader.rs).

import (
	"errors"
	"fmt"
	"io"
	"strconv"
	"strings"
)

// recIter walks BIFF12 records. buf keeps Rust Vec semantics: it only grows unless cleared.
type recIter struct {
	data []byte
	pos  int
	buf  []byte
}

func (it *recIter) readU8() (byte, error) {
	if it.pos >= len(it.data) {
		return 0, io.ErrUnexpectedEOF
	}
	b := it.data[it.pos]
	it.pos++
	return b, nil
}

func (it *recIter) readType() (uint16, error) {
	b, err := it.readU8()
	if err != nil {
		return 0, err
	}
	if b&0x80 == 0x80 {
		b2, err := it.readU8()
		if err != nil {
			return 0, err
		}
		return uint16(b&0x7F) + uint16(b2&0x7F)<<7, nil
	}
	return uint16(b), nil
}

func (it *recIter) fill() (int, error) {
	b, err := it.readU8()
	if err != nil {
		return 0, err
	}
	n := int(b & 0x7F)
	for i := 1; i < 4; i++ {
		if b&0x80 == 0 {
			break
		}
		b, err = it.readU8()
		if err != nil {
			return 0, err
		}
		n += int(b&0x7F) << (7 * i)
	}
	if len(it.buf) < n {
		nb := make([]byte, n)
		copy(nb, it.buf)
		it.buf = nb
	}
	if it.pos+n > len(it.data) {
		copy(it.buf, it.data[it.pos:])
		it.pos = len(it.data)
		return 0, io.ErrUnexpectedEOF
	}
	copy(it.buf[:n], it.data[it.pos:it.pos+n])
	it.pos += n
	return n, nil
}

func (it *recIter) clear() { it.buf = it.buf[:0] }

type skipBound struct {
	typ    uint16
	end    uint16
	hasEnd bool
}

func (it *recIter) nextSkipBlocks(want uint16, bounds []skipBound) (int, error) {
	for {
		t, err := it.readType()
		if err != nil {
			return 0, err
		}
		n, err := it.fill()
		if err != nil {
			return 0, err
		}
		if t == want {
			return n, nil
		}
		for _, b := range bounds {
			if b.typ == t {
				if b.hasEnd {
					for {
						t2, err := it.readType()
						if err != nil {
							return 0, err
						}
						if t2 == b.end {
							break
						}
						if _, err := it.fill(); err != nil {
							return 0, err
						}
					}
					if _, err := it.fill(); err != nil {
						return 0, err
					}
				}
				break
			}
		}
	}
}

// wideStr decodes an XLWideString at the start of b; returns the string and its byte length.
func wideStr(b []byte) (string, int, error) {
	if len(b) < 4 {
		panic("wide string header out of range")
	}
	n := int(u32(b))
	if len(b) < 4+n*2 {
		return "", 0, fmt.Errorf("wide str length exceeds buffer length (%d > %d)", 4+n*2, len(b))
	}
	return decodeWithBOM(encUTF16LE, b[4:4+n*2]), 4 + n*2, nil
}

type xlsbSheet struct{ name, path string }

// Xlsb is an opened xlsb workbook.
type Xlsb struct {
	z            *zipPkg
	externSheets []string
	sheets       []xlsbSheet
	strings      []string
	formats      []cellFormat
	is1904       bool
	meta         []Sheet
	names        []Name
	pictures     []Picture
}

func (x *Xlsb) Format() string                                 { return "xlsb" }
func (x *Xlsb) Sheets() []Sheet                                { return x.meta }
func (x *Xlsb) DefinedNames() []Name                           { return x.names }
func (x *Xlsb) MergedCells(string) ([]Dimensions, bool, error) { return nil, false, nil }

func (x *Xlsb) iter(path string) (*recIter, error) {
	b, err := x.z.read(path)
	if err != nil {
		if err == errZipNotFound {
			return nil, errors.New("file not found: " + path)
		}
		return nil, err
	}
	return &recIter{data: b}, nil
}

// OpenXlsb opens an xlsb package held in memory.
func OpenXlsb(data []byte) (wb Workbook, err error) {
	defer func() {
		if p := recover(); p != nil {
			wb, err = nil, fmt.Errorf("xlsb: malformed file (%v)", p)
		}
	}()
	if isEncryptedCfb(data) {
		return nil, errors.New("workbook is password protected")
	}
	z, err := openZip(data)
	if err != nil {
		return nil, err
	}
	x := &Xlsb{z: z}
	if err := x.readSharedStrings(); err != nil {
		return nil, err
	}
	if err := x.readStyles(); err != nil {
		return nil, err
	}
	rels, err := x.readRelationships()
	if err != nil {
		return nil, err
	}
	if err := x.readWorkbook(rels); err != nil {
		return nil, err
	}
	if x.pictures, err = zipMediaPictures(z, "xl/media"); err != nil {
		return nil, err
	}
	return x, nil
}

func (x *Xlsb) readSharedStrings() error {
	it, err := x.iter("xl/sharedStrings.bin")
	if err != nil {
		return nil
	}
	if _, err := it.nextSkipBlocks(0x009F, nil); err != nil {
		return err
	}
	n := int(u32(it.buf[4:8]))
	for i := 0; i < n; i++ {
		if _, err := it.nextSkipBlocks(0x0013, []skipBound{{0x0023, 0x0024, true}}); err != nil {
			return err
		}
		s, _, err := wideStr(it.buf[1:])
		if err != nil {
			return err
		}
		x.strings = append(x.strings, s)
	}
	return nil
}

func (x *Xlsb) readStyles() error {
	it, err := x.iter("xl/styles.bin")
	if err != nil {
		return nil
	}
	numFmts := map[uint16]cellFormat{}
	for {
		t, err := it.readType()
		if err != nil {
			return err
		}
		switch t {
		case 0x0267:
			if _, err := it.fill(); err != nil {
				return err
			}
			n := int(u32(it.buf))
			for i := 0; i < n; i++ {
				if _, err := it.nextSkipBlocks(0x002C, nil); err != nil {
					return err
				}
				code := u16(it.buf)
				s, _, err := wideStr(it.buf[2:])
				if err != nil {
					return err
				}
				numFmts[code] = detectCustomNumberFormat(s)
			}
		case 0x0269:
			if _, err := it.fill(); err != nil {
				return err
			}
			n := int(u32(it.buf))
			for i := 0; i < n; i++ {
				if _, err := it.nextSkipBlocks(0x002F, nil); err != nil {
					return err
				}
				code := u16(it.buf[2:4])
				switch builtinFormatByCode(code) {
				case fmtDateTime:
					x.formats = append(x.formats, fmtDateTime)
				case fmtTimeDelta:
					x.formats = append(x.formats, fmtTimeDelta)
				default:
					if f, ok := numFmts[code]; ok {
						x.formats = append(x.formats, f)
					} else {
						x.formats = append(x.formats, fmtOther)
					}
				}
			}
			return nil
		}
		it.clear()
	}
}

func (x *Xlsb) readRelationships() (map[string]string, error) {
	rels := map[string]string{}
	f, ok := x.z.byName["xl/_rels/workbook.bin.rels"]
	if !ok {
		return rels, nil
	}
	rc, err := f.Open()
	if err != nil {
		return nil, err
	}
	b, err := io.ReadAll(rc)
	rc.Close()
	if err != nil {
		return nil, err
	}
	xr := newXMLReader(b)
	for {
		ev, err := xr.next()
		if err != nil {
			return nil, err
		}
		if ev.kind == evStart && ev.isName("Relationship") {
			v, has, err := getAttrs(ev.attrs, "Id", "Target")
			if err != nil {
				return nil, err
			}
			if has[0] && has[1] {
				t, err := decodeAttr(v[1])
				if err != nil {
					return nil, err
				}
				rels[v[0]] = t
			}
		} else if ev.kind == evEOF {
			return rels, nil
		}
	}
}

func (x *Xlsb) readWorkbook(rels map[string]string) error {
	it, err := x.iter("xl/workbook.bin")
	if err != nil {
		return err
	}
loop1:
	for {
		t, err := it.readType()
		if err != nil {
			return err
		}
		switch t {
		case 0x0099:
			if _, err := it.fill(); err != nil {
				return err
			}
			x.is1904 = it.buf[0]&1 != 0
		case 0x009C:
			n, err := it.fill()
			if err != nil {
				return err
			}
			buf := it.buf
			relLen := u32(buf[8:n])
			if relLen != 0xFFFF_FFFF {
				rl := int(relLen) * 2
				relid := decodeWithBOM(encUTF16LE, buf[12:12+rl])
				target, ok := rels[relid]
				if !ok {
					panic("relationship id not found")
				}
				path := "xl/" + target
				var vis SheetVisible
				switch u32(buf) {
				case 0:
					vis = Visible
				case 1:
					vis = Hidden
				case 2:
					vis = VeryHidden
				default:
					return errors.New("unrecognized BoundSheet8:hsState")
				}
				parts := strings.Split(path, "/")
				var typ SheetType
				comp := ""
				if len(parts) > 1 {
					comp = parts[1]
				}
				switch comp {
				case "worksheets":
					typ = WorkSheet
				case "chartsheets":
					typ = ChartSheet
				case "dialogsheets":
					typ = DialogSheet
				default:
					return errors.New("unrecognized BoundSheet8:dt " + path)
				}
				name, _, err := wideStr(buf[12+rl : n])
				if err != nil {
					return err
				}
				x.meta = append(x.meta, Sheet{Name: name, Type: typ, Visible: vis})
				x.sheets = append(x.sheets, xlsbSheet{name, path})
			}
		case 0x0090:
			break loop1
		default:
			if _, err := it.fill(); err != nil {
				return err
			}
		}
		it.clear()
	}
	var names []Name
	for {
		t, err := it.readType()
		if err != nil {
			return err
		}
		switch t {
		case 0x016A:
			if _, err := it.fill(); err != nil {
				return err
			}
			buf := it.buf
			cxti := int(u32(buf[:4]))
			rest := buf[4:]
			var ext []string
			for i := 0; i < cxti && i*12 < len(rest); i++ {
				end := min(i*12+12, len(rest))
				chunk := rest[i*12 : end]
				p := i32(chunk[4:8])
				switch {
				case p == -2:
					ext = append(ext, "#ThisWorkbook")
				case p == -1:
					ext = append(ext, "#InvalidWorkSheet")
				case p >= 0 && int(p) < len(x.sheets):
					ext = append(ext, x.sheets[p].name)
				default:
					ext = append(ext, "#Unknown")
				}
			}
			x.externSheets = ext
		case 0x0027:
			n, err := it.fill()
			if err != nil {
				return err
			}
			buf := it.buf
			name, sl, err := wideStr(buf[9:n])
			if err != nil {
				return err
			}
			rgceLen := int(u32(buf[9+sl:]))
			rgce := buf[13+sl : 13+sl+rgceLen]
			f, err := xlsbParseFormula(rgce, x.externSheets, names)
			if err != nil {
				return err
			}
			names = append(names, Name{name, f})
		case 0x009D, 0x0225, 0x018D, 0x0180, 0x009A, 0x0252, 0x0229, 0x009B, 0x0084:
			x.names = names
			return nil
		}
	}
}

// ---- cells ----

type xlsbCellReader struct {
	x   *Xlsb
	it  *recIter
	row uint32
}

func (x *Xlsb) cellReader(name string) (*xlsbCellReader, error) {
	path := ""
	found := false
	for _, s := range x.sheets {
		if s.name == name {
			path, found = s.path, true
			break
		}
	}
	if !found {
		return nil, fmt.Errorf("worksheet %q not found", name)
	}
	it, err := x.iter(path)
	if err != nil {
		return nil, err
	}
	if _, err := it.nextSkipBlocks(0x0094, []skipBound{{typ: 0x0081}, {typ: 0x0093}}); err != nil {
		return nil, err
	}
	_ = it.buf[:16] // BrtWsDim (bounds checked like the Rust slice)
	if _, err := it.nextSkipBlocks(0x0091, []skipBound{
		{0x0085, 0x0086, true}, {0x0025, 0x0026, true}, {typ: 0x01E5}, {0x0186, 0x0187, true},
	}); err != nil {
		return nil, err
	}
	return &xlsbCellReader{x: x, it: it}, nil
}

func (cr *xlsbCellReader) cellFormat() *cellFormat {
	b := cr.it.buf
	style := int(uint32(b[4]) | uint32(b[5])<<8 | uint32(b[6])<<16)
	return fmtAt(cr.x.formats, style)
}

func (cr *xlsbCellReader) nextCell() (Cell, bool, error) {
	it := cr.it
	for {
		t, err := it.readType()
		if err != nil {
			return Cell{}, false, err
		}
		if _, err := it.fill(); err != nil {
			return Cell{}, false, err
		}
		buf := it.buf
		var v Data
		switch t {
		case 0x0002:
			d100 := buf[8]&1 != 0
			isInt := buf[8]&2 != 0
			buf[8] &= 0xFC
			if isInt {
				iv := int64(i32(buf[8:12]) >> 2)
				if d100 {
					v = formatExcelF64(float64(iv)/100.0, cr.cellFormat(), cr.x.is1904)
				} else {
					v = Data{Kind: Int, I: iv}
				}
			} else {
				var fb [8]byte
				copy(fb[4:], buf[8:12])
				f := f64le(fb[:])
				if d100 {
					f /= 100.0
				}
				v = formatExcelF64(f, cr.cellFormat(), cr.x.is1904)
			}
		case 0x0003:
			c, ok := errCode(buf[8])
			if !ok {
				return Cell{}, false, fmt.Errorf("unsupported cell error code %X", buf[8])
			}
			v = Data{Kind: Error, E: c}
		case 0x0004, 0x000A:
			v = Data{Kind: Bool, B: buf[8] != 0}
		case 0x0005, 0x0009:
			v = formatExcelF64(f64le(buf[8:16]), cr.cellFormat(), cr.x.is1904)
		case 0x0006, 0x0008:
			s, _, err := wideStr(buf[8:])
			if err != nil {
				return Cell{}, false, err
			}
			v = Data{Kind: String, S: s}
		case 0x0007:
			isst := int(u32(buf[8:12]))
			v = Data{Kind: String, S: cr.x.strings[isst]}
		case 0x0000:
			cr.row = u32(buf)
			if cr.row > 0x0010_0000 {
				return Cell{}, false, nil
			}
			continue
		case 0x0092:
			return Cell{}, false, nil
		default:
			continue
		}
		return Cell{cr.row, u32(buf), v}, true, nil
	}
}

func (cr *xlsbCellReader) nextFormula() (FCell, bool, error) {
	it := cr.it
	for {
		t, err := it.readType()
		if err != nil {
			return FCell{}, false, err
		}
		if _, err := it.fill(); err != nil {
			return FCell{}, false, err
		}
		buf := it.buf
		var f []byte
		switch t {
		case 0x0008:
			cch := int(u32(buf[8:]))
			f = buf[14+cch*2:]
		case 0x0009:
			f = buf[18:]
		case 0x000A, 0x000B:
			f = buf[11:]
		case 0x0000:
			cr.row = u32(buf)
			if cr.row > 0x0010_0000 {
				return FCell{}, false, nil
			}
			continue
		case 0x0092:
			return FCell{}, false, nil
		default:
			continue
		}
		cce := int(u32(f))
		s, err := xlsbParseFormula(f[4:4+cce], cr.x.externSheets, cr.x.names)
		if err != nil {
			return FCell{}, false, err
		}
		return FCell{cr.row, u32(buf), s}, true, nil
	}
}

func (x *Xlsb) WorksheetRange(name string) (Range, error) {
	cr, err := x.cellReader(name)
	if err != nil {
		return Range{}, err
	}
	var cells []Cell
	for {
		c, ok, err := cr.nextCell()
		if err != nil {
			return Range{}, err
		}
		if !ok {
			break
		}
		if c.Val.Kind != Empty {
			cells = append(cells, c)
		}
	}
	return RangeFromSparse(cells), nil
}

func (x *Xlsb) WorksheetFormula(name string) (FRange, error) {
	cr, err := x.cellReader(name)
	if err != nil {
		return FRange{}, err
	}
	var cells []FCell
	for {
		c, ok, err := cr.nextFormula()
		if err != nil {
			return FRange{}, err
		}
		if !ok {
			break
		}
		if c.Val != "" {
			cells = append(cells, c)
		}
	}
	return FRangeFromSparse(cells), nil
}

// ---- formulas ----

func xlsbParseFormula(rgce []byte, sheets []string, names []Name) (string, error) {
	if len(rgce) == 0 {
		return "", nil
	}
	var stack []int
	f := &fbuf{}
	for len(rgce) > 0 {
		ptg := rgce[0]
		rgce = rgce[1:]
		switch ptg {
		case 0x3a, 0x5a, 0x7a:
			ixti := u16(rgce[0:2])
			stack = append(stack, f.len())
			f.push(sheets[ixti])
			f.push("!$")
			f.pushColumn(uint32(u16(rgce[6:8])))
			f.pushByte('$')
			f.push(strconv.FormatUint(uint64(u32(rgce[2:6])+1), 10))
			rgce = rgce[8:]
		case 0x3b, 0x5b, 0x7b:
			ixti := u16(rgce[0:2])
			stack = append(stack, f.len())
			f.push(sheets[ixti])
			f.push("!$")
			f.pushColumn(uint32(u16(rgce[10:12])))
			f.pushByte('$')
			f.push(strconv.FormatUint(uint64(u32(rgce[2:6])+1), 10))
			f.push(":$")
			f.pushColumn(uint32(u16(rgce[12:14])))
			f.pushByte('$')
			f.push(strconv.FormatUint(uint64(u32(rgce[6:10])+1), 10))
			rgce = rgce[14:]
		case 0x3c, 0x5c, 0x7c:
			ixti := u16(rgce[0:2])
			stack = append(stack, f.len())
			f.push(sheets[ixti])
			f.push("!#REF!")
			rgce = rgce[8:]
		case 0x3d, 0x5d, 0x7d:
			ixti := u16(rgce[0:2])
			stack = append(stack, f.len())
			f.push(sheets[ixti])
			f.push("!#REF!")
			rgce = rgce[14:]
		case 0x01:
			stack = append(stack, f.len())
			rgce = rgce[4:]
		case 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F, 0x10, 0x11:
			if len(stack) == 0 {
				return "", errStackLen()
			}
			e2 := stack[len(stack)-1]
			stack = stack[:len(stack)-1]
			s := f.splitOff(e2)
			f.push(binOps[ptg])
			f.push(s)
		case 0x12:
			if len(stack) == 0 {
				return "", errStackLen()
			}
			f.insert(stack[len(stack)-1], "+")
		case 0x13:
			if len(stack) == 0 {
				return "", errStackLen()
			}
			f.insert(stack[len(stack)-1], "-")
		case 0x14:
			f.pushByte('%')
		case 0x15:
			if len(stack) == 0 {
				return "", errStackLen()
			}
			f.insert(stack[len(stack)-1], "(")
			f.pushByte(')')
		case 0x16:
			stack = append(stack, f.len())
		case 0x17:
			stack = append(stack, f.len())
			f.pushByte('"')
			cch := int(u16(rgce[0:2]))
			f.push(decodeWithBOM(encUTF16LE, rgce[2:2+2*cch]))
			f.pushByte('"')
			rgce = rgce[2+2*cch:]
		case 0x18:
			stack = append(stack, f.len())
			eptg := rgce[0]
			rgce = rgce[1:]
			switch eptg {
			case 0x19:
				rgce = rgce[12:]
			case 0x1D:
				rgce = rgce[4:]
			default:
				return "", fmt.Errorf("unsupported etpg %X", eptg)
			}
		case 0x19:
			eptg := rgce[0]
			rgce = rgce[1:]
			switch eptg {
			case 0x01, 0x02, 0x08, 0x20, 0x21, 0x40, 0x41, 0x80:
				rgce = rgce[2:]
			case 0x04:
				rgce = rgce[10:]
			case 0x10:
				rgce = rgce[2:]
				if len(stack) == 0 {
					return "", errStackLen()
				}
				s := f.splitOff(stack[len(stack)-1])
				f.push("SUM(" + s + ")")
			default:
				return "", fmt.Errorf("unsupported etpg %X", eptg)
			}
		case 0x1C:
			stack = append(stack, f.len())
			e := rgce[0]
			rgce = rgce[1:]
			switch e {
			case 0x00:
				f.push("#NULL!")
			case 0x07:
				f.push("#DIV/0!")
			case 0x0F:
				f.push("#VALUE!")
			case 0x17:
				f.push("#REF!")
			case 0x1D:
				f.push("#NAME?")
			case 0x24:
				f.push("#NUM!")
			case 0x2A:
				f.push("#N/A")
			case 0x2B:
				f.push("#GETTING_DATA")
			default:
				return "", fmt.Errorf("unsupported BErr %X", e)
			}
		case 0x1D:
			stack = append(stack, f.len())
			if rgce[0] == 0 {
				f.push("FALSE")
			} else {
				f.push("TRUE")
			}
			rgce = rgce[1:]
		case 0x1E:
			stack = append(stack, f.len())
			f.push(strconv.Itoa(int(u16(rgce))))
			rgce = rgce[2:]
		case 0x1F:
			stack = append(stack, f.len())
			f.push(formatF64(f64le(rgce)))
			rgce = rgce[8:]
		case 0x20, 0x40, 0x60:
			stack = append(stack, f.len())
			rgce = rgce[14:]
		case 0x21, 0x22, 0x41, 0x42, 0x61, 0x62:
			var iftab, argc int
			if ptg == 0x22 || ptg == 0x42 || ptg == 0x62 {
				iftab = int(u16(rgce[1:]))
				argc = int(rgce[0])
				rgce = rgce[3:]
			} else {
				iftab = int(u16(rgce))
				if iftab > ftabLen {
					return "", fmt.Errorf("unsupported iftab %X", iftab)
				}
				rgce = rgce[2:]
				argc = int(ftabArgc[iftab])
			}
			if len(stack) < argc {
				return "", errStackLen()
			}
			if argc > 0 {
				argsStart := len(stack) - argc
				args := append([]int(nil), stack[argsStart:]...)
				stack = stack[:argsStart]
				start := args[0]
				for i := range args {
					args[i] -= start
				}
				fargs := f.splitOff(start)
				stack = append(stack, f.len())
				args = append(args, len(fargs))
				f.push(ftab[iftab])
				f.pushByte('(')
				for i := 0; i+1 < len(args); i++ {
					f.push(fargs[args[i]:args[i+1]])
					f.pushByte(',')
				}
				f.b = f.b[:len(f.b)-1]
				f.pushByte(')')
			} else {
				stack = append(stack, f.len())
				f.push(ftab[iftab])
				f.push("()")
			}
		case 0x23, 0x43, 0x63:
			iname := int(u32(rgce)) - 1
			stack = append(stack, f.len())
			if iname >= 0 && iname < len(names) {
				f.push(names[iname].Name)
			}
			rgce = rgce[4:]
		case 0x24, 0x44, 0x64:
			row := u32(rgce) + 1
			col := uint16(rgce[4]) | uint16(rgce[5]&0x3F)<<8
			stack = append(stack, f.len())
			if rgce[5]&0x80 != 0x80 {
				f.pushByte('$')
			}
			f.pushColumn(uint32(col))
			if rgce[5]&0x40 != 0x40 {
				f.pushByte('$')
			}
			f.push(strconv.FormatUint(uint64(row), 10))
			rgce = rgce[6:]
		case 0x25, 0x45, 0x65:
			stack = append(stack, f.len())
			f.pushByte('$')
			f.pushColumn(uint32(u16(rgce[8:10])))
			f.pushByte('$')
			f.push(strconv.FormatUint(uint64(u32(rgce[0:4])+1), 10))
			f.push(":$")
			f.pushColumn(uint32(u16(rgce[10:12])))
			f.pushByte('$')
			f.push(strconv.FormatUint(uint64(u32(rgce[4:8])+1), 10))
			rgce = rgce[12:]
		case 0x2A, 0x4A, 0x6A:
			stack = append(stack, f.len())
			f.push("#REF!")
			rgce = rgce[6:]
		case 0x2B, 0x4B, 0x6B:
			stack = append(stack, f.len())
			f.push("#REF!")
			rgce = rgce[12:]
		case 0x29, 0x49, 0x69:
			cce := int(u16(rgce))
			rgce = rgce[2:]
			sub, err := xlsbParseFormula(rgce[:cce], sheets, names)
			if err != nil {
				return "", err
			}
			stack = append(stack, f.len())
			f.push(sub)
			rgce = rgce[cce:]
		case 0x39, 0x59, 0x79:
			stack = append(stack, f.len())
			f.push("EXTERNAL_WB_NAME")
			rgce = rgce[6:]
		default:
			return "", fmt.Errorf("unsupported ptg %X", ptg)
		}
	}
	if len(stack) == 1 {
		return string(f.b), nil
	}
	return "", errStackLen()
}
