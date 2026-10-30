package calamine

// BIFF2-BIFF8 .xls reader (port of calamine src/xls.rs).

import (
	"encoding/binary"
	"errors"
	"fmt"
	"math"
	"strconv"
	"strings"
)

type biffVersion int

const (
	biff2 biffVersion = iota
	biff3
	biff4
	biff5
	biff8
)

func (b biffVersion) pre8() bool { return b != biff8 }

func u16(b []byte) uint16 { return binary.LittleEndian.Uint16(b) }
func u32(b []byte) uint32 { return binary.LittleEndian.Uint32(b) }
func i16(b []byte) int16  { return int16(binary.LittleEndian.Uint16(b)) }
func i32(b []byte) int32  { return int32(binary.LittleEndian.Uint32(b)) }
func f64le(b []byte) float64 {
	return math.Float64frombits(binary.LittleEndian.Uint64(b))
}

type xlsSheetData struct {
	rng     Range
	formula FRange
	merged  []Dimensions
}

type xti struct {
	itabFirst int16
}

// Xls is an opened .xls workbook. Everything is parsed at open time.
type Xls struct {
	sheets   map[string]*xlsSheetData
	meta     []Sheet
	names    []Name
	cfb      *cfb
	reader   *fileReader
	pictures []Picture
}

func (x *Xls) Format() string       { return "xls" }
func (x *Xls) Sheets() []Sheet      { return x.meta }
func (x *Xls) DefinedNames() []Name { return x.names }
func (x *Xls) WorksheetRange(name string) (Range, error) {
	s, ok := x.sheets[name]
	if !ok {
		return Range{}, fmt.Errorf("worksheet %q not found", name)
	}
	return s.rng, nil
}
func (x *Xls) WorksheetFormula(name string) (FRange, error) {
	s, ok := x.sheets[name]
	if !ok {
		return FRange{}, fmt.Errorf("worksheet %q not found", name)
	}
	return s.formula, nil
}
func (x *Xls) MergedCells(name string) ([]Dimensions, bool, error) {
	s, ok := x.sheets[name]
	if !ok {
		return nil, true, fmt.Errorf("worksheet %q not found", name)
	}
	return s.merged, true, nil
}

// OpenXls parses an xls file held in memory.
func OpenXls(data []byte) (wb *Xls, err error) {
	defer func() {
		if r := recover(); r != nil {
			wb, err = nil, fmt.Errorf("xls: malformed file (%v)", r)
		}
	}()
	r := &fileReader{buf: data}
	c, err := newCfb(r, len(data))
	if err != nil {
		return nil, err
	}
	x := &Xls{sheets: map[string]*xlsSheetData{}, cfb: c, reader: r}
	if err := x.parseWorkbook(c, r); err != nil {
		return nil, err
	}
	return x, nil
}

// ---- records ----

type record struct {
	typ  uint16
	data []byte
	cont [][]byte
}

func (r *record) continueRecord() bool {
	if len(r.cont) == 0 {
		return false
	}
	r.data = r.cont[0]
	r.cont = r.cont[1:]
	return true
}

func (r *record) skip(n int) error {
	for n > 0 {
		if len(r.data) == 0 && !r.continueRecord() {
			return errors.New("continue record too short")
		}
		l := min(n, len(r.data))
		r.data = r.data[l:]
		n -= l
	}
	return nil
}

type recordIter struct{ stream []byte }

// next returns (record, ok, error). ok=false at the end of the stream.
func (it *recordIter) next() (*record, bool, error) {
	if len(it.stream) < 4 {
		if len(it.stream) == 0 {
			return nil, false, nil
		}
		return nil, false, errors.New("end of stream: record type and length")
	}
	t := u16(it.stream)
	l := int(u16(it.stream[2:]))
	if len(it.stream) < l+4 {
		return nil, false, errors.New("end of stream: record length")
	}
	d := it.stream[4 : l+4]
	next := it.stream[l+4:]
	it.stream = next
	var cont [][]byte
	if len(next) > 4 && u16(next) == 0x003C {
		for len(it.stream) > 4 && u16(it.stream) == 0x003C {
			cl := int(u16(it.stream[2:]))
			if len(it.stream) < cl+4 {
				return nil, false, errors.New("end of stream: continue record length")
			}
			cont = append(cont, it.stream[4:cl+4])
			it.stream = it.stream[cl+4:]
		}
	}
	return &record{typ: t, data: d, cont: cont}, true, nil
}

// ---- workbook ----

func (x *Xls) parseWorkbook(c *cfb, rd *fileReader) error {
	var stream []byte
	var err error
	for _, n := range []string{"Workbook", "Book", "WORKBOOK", "BOOK"} {
		stream, err = c.getStream(n, rd)
		if err == nil {
			break
		}
		if !errors.Is(err, errStreamNotFound) {
			return err
		}
	}
	if err != nil {
		return err
	}

	type sheetPos struct {
		pos  int
		name string
	}
	var sheetNames []sheetPos
	var strs []string
	type lbl struct {
		name    string
		hasIdx  bool
		idx     int
		formula string
	}
	var defNames []lbl
	var xtis []xti
	formats := map[uint16]cellFormat{}
	var xfs []uint16
	biff := biff8
	enc, err := encodingFromCodepage(1200)
	if err != nil {
		return err
	}
	encoding := xlsEncoding{enc}
	is1904 := false
	var drawGroup []byte

	it := recordIter{stream: stream}
	for {
		r, ok, err := it.next()
		if err != nil {
			return err
		}
		if !ok {
			break
		}
		done := false
		switch r.typ {
		case 0x002F:
			if u16(r.data) != 0 {
				return errors.New("workbook is password protected")
			}
		case 0x0042:
			e, err := encodingFromCodepage(u16(r.data))
			if err != nil {
				return err
			}
			encoding = xlsEncoding{e}
		case 0x0022:
			if u16(r.data) == 1 {
				is1904 = true
			}
		case 0x041E:
			if idx, f, err := parseFormat(r, encoding, biff); err == nil {
				formats[idx] = f
			}
		case 0x00E0:
			if len(r.data) < 4 {
				return errors.New("invalid xf length")
			}
			xfs = append(xfs, u16(r.data[2:]))
		case 0x0085:
			pos, sh, err := parseSheetMetadata(r, encoding, biff)
			if err != nil {
				return err
			}
			x.meta = append(x.meta, sh)
			sheetNames = append(sheetNames, sheetPos{pos, sh.Name})
		case 0x0809:
			biff = parseBof(r)
		case 0x0018:
			name, hasIdx, idx, f, err := parseLbl(r, encoding, biff)
			if err != nil {
				return err
			}
			defNames = append(defNames, lbl{name, hasIdx, idx, f})
		case 0x0017:
			if biff == biff8 {
				cxti := int(u16(r.data))
				d := r.data[2:]
				for i := 0; i < cxti && (i+1)*6 <= len(d); i++ {
					xtis = append(xtis, xti{itabFirst: i16(d[i*6+2:])})
				}
			}
		case 0x00FC:
			strs, err = parseSst(r, encoding)
			if err != nil {
				return err
			}
		case 0x00EB:
			drawGroup = append(drawGroup, r.data...)
			for _, c := range r.cont {
				drawGroup = append(drawGroup, c...)
			}
		case 0x000A:
			done = true
		}
		if done {
			break
		}
	}

	if biff.pre8() && len(xtis) == 0 {
		for i := range sheetNames {
			xtis = append(xtis, xti{itabFirst: int16(i)})
		}
	}
	cellFormats := make([]cellFormat, len(xfs))
	for i, f := range xfs {
		if s, ok := formats[f]; ok {
			cellFormats[i] = s
		} else {
			cellFormats[i] = builtinFormatByCode(f)
		}
	}

	names := make([]Name, len(defNames))
	for i, d := range defNames {
		f := d.formula
		if d.hasIdx {
			sh := "#REF"
			if d.idx < len(xtis) {
				t := int(xtis[d.idx].itabFirst)
				if t >= 0 && t < len(sheetNames) {
					sh = sheetNames[t].name
				}
			}
			f = sh + "!" + f
		}
		names[i] = Name{d.name, f}
	}

	fmlaSheetNames := make([]string, len(sheetNames))
	for i, s := range sheetNames {
		fmlaSheetNames[i] = s.name
	}
	ctx := &xlsFormulaCtx{sheets: fmlaSheetNames, names: names, xtis: xtis, enc: encoding, biff: biff}

	for _, sp := range sheetNames {
		if sp.pos > len(stream) {
			panic("sheet offset beyond stream")
		}
		sit := recordIter{stream: stream[sp.pos:]}
		var cells []Cell
		var formulas []FCell
		var fpos [2]uint32
		var merged []Dimensions
		seenBof := false
		depth := 0
	sheetLoop:
		for {
			r, ok, err := sit.next()
			if err != nil {
				return err
			}
			if !ok {
				break
			}
			if depth > 0 {
				switch r.typ {
				case 0x0809:
					depth++
				case 0x000A:
					depth--
				}
				continue
			}
			switch r.typ {
			case 0x0809:
				if seenBof {
					depth++
				} else {
					seenBof = true
				}
			case 0x0200:
				if _, err := parseDimensions(r.data); err != nil {
					return err
				}
			case 0x0203:
				c, err := parseNumber(r.data, cellFormats, is1904)
				if err != nil {
					return err
				}
				cells = append(cells, c)
			case 0x0204, 0x00D6:
				c, err := parseLabel(r.data, encoding, biff)
				if err != nil {
					return err
				}
				cells = append(cells, c)
			case 0x0205:
				c, err := parseBoolErr(r.data)
				if err != nil {
					return err
				}
				cells = append(cells, c)
			case 0x0207:
				s, err := parseString(r.data, encoding, biff)
				if err != nil {
					return err
				}
				cells = append(cells, Cell{fpos[0], fpos[1], Data{Kind: String, S: s}})
			case 0x027E:
				if len(r.data) < 10 {
					return errors.New("invalid rk length")
				}
				cells = append(cells, Cell{uint32(u16(r.data)), uint32(u16(r.data[2:])), rkNum(r.data[4:10], cellFormats, is1904)})
			case 0x00FD:
				if len(r.data) < 10 {
					return errors.New("invalid label sst length")
				}
				i := int(u32(r.data[6:]))
				if i >= 0 && i < len(strs) {
					cells = append(cells, Cell{uint32(u16(r.data)), uint32(u16(r.data[2:])), Data{Kind: String, S: strs[i]}})
				}
			case 0x00BD:
				if err := parseMulRk(r.data, &cells, cellFormats, is1904); err != nil {
					return err
				}
			case 0x00E5:
				count := int(u16(r.data))
				for i := 0; i < count; i++ {
					o := 2 + i*8
					merged = append(merged, Dimensions{
						StartRow: uint32(u16(r.data[o:])), EndRow: uint32(u16(r.data[o+2:])),
						StartCol: uint32(u16(r.data[o+4:])), EndCol: uint32(u16(r.data[o+6:])),
					})
				}
			case 0x000A:
				break sheetLoop
			case 0x0006:
				if len(r.data) < 20 {
					return errors.New("invalid formula length")
				}
				row := u16(r.data)
				col := u16(r.data[2:])
				format := fmtAt(cellFormats, int(u16(r.data[4:])))
				fpos = [2]uint32{uint32(row), uint32(col)}
				v, has, err := parseFormulaValue(r.data[6:14], format, is1904)
				if err != nil {
					return err
				}
				if has {
					cells = append(cells, Cell{fpos[0], fpos[1], v})
				}
				f, ferr := ctx.parseFormula(r.data[20:])
				if ferr != nil {
					f = fmt.Sprintf("Unrecognised formula for cell (%d, %d): %s", row, col, ferr.Error())
				}
				formulas = append(formulas, FCell{fpos[0], fpos[1], f})
			}
		}
		x.sheets[sp.name] = &xlsSheetData{rng: RangeFromSparse(cells), formula: FRangeFromSparse(formulas), merged: merged}
	}
	x.names = names
	if len(drawGroup) > 0 {
		pics, err := parseArtPictures(drawGroup)
		if err != nil {
			return err
		}
		x.pictures = pics
	}
	return nil
}

func parseBof(r *record) biffVersion {
	dt := uint16(0)
	v := u16(r.data[:2])
	if len(r.data) >= 4 {
		dt = u16(r.data[2:])
	}
	switch v {
	case 0x0200, 0x0002, 0x0007:
		return biff2
	case 0x0300:
		return biff3
	case 0x0400:
		return biff4
	case 0x0500:
		return biff5
	case 0x0600:
		return biff8
	case 0:
		if dt == 0x1000 {
			return biff5
		}
		return biff8
	}
	return biff8
}

func parseSheetMetadata(r *record, enc xlsEncoding, biff biffVersion) (int, Sheet, error) {
	pos := int(u32(r.data))
	var vis SheetVisible
	switch r.data[4] & 0x3F {
	case 0:
		vis = Visible
	case 1:
		vis = Hidden
	case 2:
		vis = VeryHidden
	default:
		return 0, Sheet{}, errors.New("unrecognized BoundSheet8:hsState")
	}
	var typ SheetType
	switch r.data[5] {
	case 0x00:
		typ = WorkSheet
	case 0x01:
		typ = MacroSheet
	case 0x02:
		typ = ChartSheet
	case 0x06:
		typ = VbaSheet
	default:
		return 0, Sheet{}, errors.New("unrecognized BoundSheet8:dt")
	}
	r.data = r.data[6:]
	name, err := parseShortString(r, enc, biff)
	if err != nil {
		return 0, Sheet{}, err
	}
	name = strings.ReplaceAll(name, "\x00", "")
	return pos, Sheet{Name: name, Type: typ, Visible: vis}, nil
}

func parseLbl(r *record, enc xlsEncoding, biff biffVersion) (string, bool, int, string, error) {
	cch := int(r.data[3])
	cce := int(u16(r.data[4:]))
	var sb strings.Builder
	if biff.pre8() {
		enc.decodeTo(r.data[14:], cch, &sb, hbNone)
	} else {
		if _, err := readUnicodeStringNoCch(enc, r.data[14:], cch, &sb); err != nil {
			return "", false, 0, "", err
		}
	}
	rgce := r.data[len(r.data)-cce:]
	hasIdx, idx, f := parseDefinedNames(rgce, biff)
	return sb.String(), hasIdx, idx, f, nil
}

func parseNumber(r []byte, formats []cellFormat, is1904 bool) (Cell, error) {
	if len(r) < 14 {
		return Cell{}, errors.New("invalid number length")
	}
	row := uint32(u16(r))
	col := uint32(u16(r[2:]))
	v := f64le(r[6:])
	return Cell{row, col, formatExcelF64(v, fmtAt(formats, int(u16(r[4:]))), is1904)}, nil
}

func parseBoolErr(r []byte) (Cell, error) {
	if len(r) < 8 {
		return Cell{}, errors.New("invalid BoolErr length")
	}
	row := uint32(u16(r))
	col := uint32(u16(r[2:]))
	switch r[7] {
	case 0:
		return Cell{row, col, Data{Kind: Bool, B: r[6] != 0}}, nil
	case 1:
		d, err := parseErr(r[6])
		if err != nil {
			return Cell{}, err
		}
		return Cell{row, col, d}, nil
	}
	return Cell{}, errors.New("unrecognized fError")
}

func errCode(e byte) (CellErrorType, bool) {
	switch e {
	case 0x00:
		return ErrNull, true
	case 0x07:
		return ErrDiv0, true
	case 0x0F:
		return ErrValue, true
	case 0x17:
		return ErrRef, true
	case 0x1D:
		return ErrName, true
	case 0x24:
		return ErrNum, true
	case 0x2A:
		return ErrNA, true
	case 0x2B:
		return ErrGettingData, true
	}
	return 0, false
}

func parseErr(e byte) (Data, error) {
	c, ok := errCode(e)
	if !ok {
		return Data{}, errors.New("unrecognized error code")
	}
	return Data{Kind: Error, E: c}, nil
}

func parseMulRk(r []byte, cells *[]Cell, formats []cellFormat, is1904 bool) error {
	if len(r) < 6 {
		return errors.New("invalid rk length")
	}
	row := u16(r)
	first := u16(r[2:])
	last := u16(r[len(r)-2:])
	n := int(uint16(last - first + 1)) // u16 arithmetic wraps like Rust release builds
	if len(r) != 6+6*n {
		return errors.New("invalid mulrk length")
	}
	body := r[4 : len(r)-2]
	col := uint32(first)
	for i := 0; i < len(body); i += 6 {
		end := min(i+6, len(body))
		*cells = append(*cells, Cell{uint32(row), col, rkNum(body[i:end], formats, is1904)})
		col++
	}
	return nil
}

func rkNum(rk []byte, formats []cellFormat, is1904 bool) Data {
	d100 := rk[2]&1 != 0
	isInt := rk[2]&2 != 0
	format := fmtAt(formats, int(u16(rk)))
	var v [8]byte
	copy(v[4:], rk[2:6])
	v[4] &= 0xFC
	if isInt {
		iv := int64(i32(v[4:8]) >> 2)
		if d100 && iv%100 != 0 {
			return formatExcelF64(float64(iv)/100.0, format, is1904)
		}
		if d100 {
			iv /= 100
		}
		return formatExcelI64(iv, format, is1904)
	}
	fv := f64le(v[:])
	if d100 {
		fv /= 100.0
	}
	return formatExcelF64(fv, format, is1904)
}

func parseShortString(r *record, enc xlsEncoding, biff biffVersion) (string, error) {
	b8 := biff == biff8
	if len(r.data) == 0 || (len(r.data) < 2 && b8) {
		return "", errors.New("invalid short string length")
	}
	cch := int(r.data[0])
	r.data = r.data[1:]
	hb := hbNone
	if b8 {
		if r.data[0]&1 != 0 {
			hb = hbTrue
		} else {
			hb = hbFalse
		}
		r.data = r.data[1:]
	}
	var sb strings.Builder
	enc.decodeTo(r.data, cch, &sb, hb)
	return sb.String(), nil
}

func parseString(r []byte, enc xlsEncoding, biff biffVersion) (string, error) {
	expected := 3
	if biff.pre8() {
		expected = 2
	}
	if len(r) < expected {
		if len(r) == 2 && u16(r) == 0 {
			return "", nil
		}
		return "", errors.New("invalid string length")
	}
	hb := hbNone
	if !biff.pre8() {
		if r[2]&1 != 0 {
			hb = hbTrue
		} else {
			hb = hbFalse
		}
	}
	cch := int(u16(r))
	var sb strings.Builder
	enc.decodeTo(r[expected:], cch, &sb, hb)
	return sb.String(), nil
}

func parseLabel(r []byte, enc xlsEncoding, biff biffVersion) (Cell, error) {
	if len(r) < 6 {
		return Cell{}, errors.New("invalid label length")
	}
	s, err := parseString(r[6:], enc, biff)
	if err != nil {
		return Cell{}, err
	}
	return Cell{uint32(u16(r)), uint32(u16(r[2:])), Data{Kind: String, S: s}}, nil
}

func parseDimensions(r []byte) (Dimensions, error) {
	var rf, rl, cf, cl uint32
	switch len(r) {
	case 10:
		rf, rl, cf, cl = uint32(u16(r)), uint32(u16(r[2:])), uint32(u16(r[4:])), uint32(u16(r[6:]))
	case 14, 16:
		rf, rl, cf, cl = u32(r), u32(r[4:]), uint32(u16(r[8:])), uint32(u16(r[10:]))
	default:
		return Dimensions{}, errors.New("invalid dimensions length")
	}
	if 0xFF < cf || cl < cf {
		cf = 0
	}
	if rl >= 1 && cl >= 1 {
		return Dimensions{rf, cf, rl - 1, cl - 1}, nil
	}
	return Dimensions{rf, cf, rf, cf}, nil
}

func parseSst(r *record, enc xlsEncoding) ([]string, error) {
	if len(r.data) < 8 {
		return nil, errors.New("invalid sst length")
	}
	var sst []string
	r.data = r.data[8:]
	for len(r.data) > 0 || r.continueRecord() {
		s, err := readRichExtendedString(r, enc)
		if err != nil {
			return nil, err
		}
		sst = append(sst, s)
	}
	return sst, nil
}

func parseFormat(r *record, enc xlsEncoding, biff biffVersion) (uint16, cellFormat, error) {
	if len(r.data) < 2 {
		return 0, fmtOther, errors.New("invalid format length")
	}
	ifmt := u16(r.data)
	switch {
	case ifmt >= 5 && ifmt <= 8, ifmt >= 23 && ifmt <= 26, ifmt >= 41 && ifmt <= 44,
		ifmt >= 63 && ifmt <= 66, ifmt >= 164 && ifmt <= 382:
	default:
		return 0, fmtOther, errors.New("invalid ifmt")
	}
	s, err := parseString(r.data[2:], enc, biff)
	if err != nil {
		return 0, fmtOther, err
	}
	return ifmt, detectCustomNumberFormat(s), nil
}

func readRichExtendedString(r *record, enc xlsEncoding) (string, error) {
	if len(r.data) == 0 {
		return "", nil
	}
	if len(r.data) < 3 {
		return "", errors.New("invalid rich extended string length")
	}
	cch := int(u16(r.data))
	flags := r.data[2]
	r.data = r.data[3:]
	high := flags&1 != 0
	cRun := 0
	cbExt := 0
	if flags&0x8 != 0 {
		cRun = int(u16(r.data))
		r.data = r.data[2:]
	}
	if flags&0x4 != 0 {
		cbExt = int(uint64(int64(i32(r.data)))) // `as usize` of an i32
		r.data = r.data[4:]
	}
	s, err := readDbcs(enc, cch, r, high)
	if err != nil {
		return "", err
	}
	if err := r.skip(cRun * 4); err != nil {
		return "", err
	}
	if cbExt < 0 {
		return "", errors.New("continue record too short")
	}
	if err := r.skip(cbExt); err != nil {
		return "", err
	}
	return s, nil
}

func readDbcs(enc xlsEncoding, n int, r *record, high bool) (string, error) {
	var sb strings.Builder
	for n > 0 {
		hb := hbFalse
		if high {
			hb = hbTrue
		}
		l, at := enc.decodeTo(r.data, n, &sb, hb)
		r.data = r.data[at:]
		n -= l
		if n > 0 {
			if r.continueRecord() {
				high = r.data[0]&1 != 0
				r.data = r.data[1:]
			} else {
				return "", errors.New("end of stream: dbcs")
			}
		}
	}
	return sb.String(), nil
}

func readUnicodeStringNoCch(enc xlsEncoding, buf []byte, n int, sb *strings.Builder) (int, error) {
	if len(buf) == 0 {
		return 0, errors.New("invalid XLUnicodeStringNoCch length")
	}
	high := buf[0]&1 != 0
	consumed := 1 + n
	hb := hbFalse
	if high {
		consumed = 1 + 2*n
		hb = hbTrue
	}
	if len(buf) < consumed {
		return 0, errors.New("invalid XLUnicodeStringNoCch length")
	}
	enc.decodeTo(buf[1:consumed], n, sb, hb)
	return consumed, nil
}

func pushColumn(col uint32, sb *strings.Builder) {
	var digits [8]byte
	n := 0
	num := uint64(col) + 1
	for num > 0 {
		digits[n] = byte('A' + (num-1)%26)
		n++
		num = (num - 1) / 26
	}
	for i := n - 1; i >= 0; i-- {
		sb.WriteByte(digits[i])
	}
}

func writeAbsCellRef(sb *strings.Builder, col, row uint32) {
	sb.WriteByte('$')
	pushColumn(col, sb)
	sb.WriteByte('$')
	sb.WriteString(strconv.FormatUint(uint64(row)+1, 10))
}

func parseDefinedNames(rgce []byte, biff biffVersion) (bool, int, string) {
	if len(rgce) == 0 {
		return false, 0, "empty rgce"
	}
	ptg := rgce[0]
	var sb strings.Builder
	switch ptg {
	case 0x3a, 0x5a, 0x7a:
		var idx int
		var row, col uint32
		if biff.pre8() {
			idx = int(u16(rgce[11:13]))
			row = uint32(u16(rgce[15:17])) & 0x3FFF
			col = uint32(rgce[17])
		} else {
			idx = int(u16(rgce[1:3]))
			row = uint32(u16(rgce[3:5]))
			col = uint32(u16(rgce[5:7]))
		}
		writeAbsCellRef(&sb, col, row)
		return true, idx, sb.String()
	case 0x3b, 0x5b, 0x7b:
		var idx int
		var rf, rl, cf, cl uint32
		if biff.pre8() {
			idx = int(u16(rgce[11:13]))
			rf = uint32(u16(rgce[15:17])) & 0x3FFF
			rl = uint32(u16(rgce[17:19])) & 0x3FFF
			cf = uint32(rgce[19])
			cl = uint32(rgce[20])
		} else {
			idx = int(u16(rgce[1:3]))
			rf = uint32(u16(rgce[3:5]))
			rl = uint32(u16(rgce[5:7]))
			cf = uint32(u16(rgce[7:9]))
			cl = uint32(u16(rgce[9:11]))
		}
		writeAbsCellRef(&sb, cf, rf)
		sb.WriteByte(':')
		writeAbsCellRef(&sb, cl, rl)
		return true, idx, sb.String()
	case 0x3c, 0x5c, 0x7c, 0x3d, 0x5d, 0x7d:
		var idx int
		if biff.pre8() {
			idx = int(u16(rgce[11:13]))
		} else {
			idx = int(u16(rgce[1:3]))
		}
		return true, idx, "#REF!"
	}
	return false, 0, fmt.Sprintf("Unsupported ptg: %x", ptg)
}

type xlsFormulaCtx struct {
	sheets []string
	names  []Name
	xtis   []xti
	enc    xlsEncoding
	biff   biffVersion
}

// fbuf is a byte-oriented string builder that supports the stack manipulation
// done by calamine's RPN-to-infix conversion (positions are byte offsets).
type fbuf struct{ b []byte }

func (f *fbuf) len() int        { return len(f.b) }
func (f *fbuf) push(s string)   { f.b = append(f.b, s...) }
func (f *fbuf) pushByte(c byte) { f.b = append(f.b, c) }
func (f *fbuf) splitOff(at int) string {
	s := string(f.b[at:])
	f.b = f.b[:at]
	return s
}
func (f *fbuf) insert(at int, s string) {
	f.b = append(f.b[:at], append([]byte(s), f.b[at:]...)...)
}

func (f *fbuf) pushColumn(col uint32) {
	var sb strings.Builder
	pushColumn(col, &sb)
	f.push(sb.String())
}

func errStackLen() error { return errors.New("StackLen") }

// formatF64 mimics Rust's `{}` Display for f64 (no exponent).
func formatF64(v float64) string {
	switch {
	case math.IsNaN(v):
		return "NaN"
	case math.IsInf(v, 1):
		return "inf"
	case math.IsInf(v, -1):
		return "-inf"
	}
	return strconv.FormatFloat(v, 'f', -1, 64)
}

func (ctx *xlsFormulaCtx) parseFormula(rgce []byte) (string, error) {
	pre8 := ctx.biff.pre8()
	var stack []int
	f := &fbuf{}
	cce := int(u16(rgce))
	rgce = rgce[2 : 2+cce]
	for len(rgce) > 0 {
		ptg := rgce[0]
		rgce = rgce[1:]
		switch ptg {
		case 0x3a, 0x5a, 0x7a:
			ixti := u16(rgce[0:2])
			rowu := u16(rgce[2:])
			colu := u16(rgce[4:])
			sh := "#REF"
			if int(ixti) < len(ctx.xtis) {
				t := int(ctx.xtis[ixti].itabFirst)
				if t >= 0 && t < len(ctx.sheets) {
					sh = ctx.sheets[t]
				}
			}
			stack = append(stack, f.len())
			f.push(sh)
			f.pushByte('!')
			col := colu << 2
			if colu&2 != 0 {
				f.pushByte('$')
			}
			f.pushColumn(uint32(col))
			if colu&1 != 0 {
				f.pushByte('$')
			}
			f.push(strconv.Itoa(int(rowu + 1)))
			rgce = rgce[6:]
		case 0x3b, 0x5b, 0x7b:
			ixti := u16(rgce[0:2])
			stack = append(stack, f.len())
			if int(ixti) < len(ctx.sheets) {
				f.push(ctx.sheets[ixti])
			} else {
				f.push("#REF")
			}
			f.pushByte('!')
			f.pushByte('$')
			f.pushColumn(uint32(u16(rgce[6:8])))
			f.push("$" + strconv.FormatUint(uint64(u16(rgce[2:4]))+1, 10) + ":$")
			f.pushColumn(uint32(u16(rgce[8:10])))
			f.push("$" + strconv.FormatUint(uint64(u16(rgce[4:6]))+1, 10))
			rgce = rgce[10:]
		case 0x3c, 0x5c, 0x7c:
			ixti := u16(rgce[0:2])
			stack = append(stack, f.len())
			if int(ixti) < len(ctx.sheets) {
				f.push(ctx.sheets[ixti])
			} else {
				f.push("#REF")
			}
			f.push("!#REF!")
			rgce = rgce[6:]
		case 0x3d, 0x5d, 0x7d:
			ixti := u16(rgce[0:2])
			stack = append(stack, f.len())
			if int(ixti) < len(ctx.sheets) {
				f.push(ctx.sheets[ixti])
			} else {
				f.push("#REF")
			}
			f.push("!#REF!")
			rgce = rgce[10:]
		case 0x01:
			stack = append(stack, f.len())
			if len(rgce) < 4 {
				return "", fmt.Errorf("Len { expected: 4, found: %d, typ: \"PtgExp\" }", len(rgce))
			}
			rgce = rgce[4:]
		case 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F, 0x10, 0x11:
			if len(stack) == 0 {
				return "", errStackLen()
			}
			e2 := stack[len(stack)-1]
			stack = stack[:len(stack)-1]
			op := binOps[ptg]
			s := f.splitOff(e2)
			f.push(op)
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
			if len(rgce) == 0 {
				return "", errors.New("Len { expected: 1, found: 0, typ: \"PtgStr\" }")
			}
			cch := int(rgce[0])
			var sb strings.Builder
			consumed, err := readUnicodeStringNoCch(ctx.enc, rgce[1:], cch, &sb)
			if err != nil {
				return "", err
			}
			f.push(sb.String())
			f.pushByte('"')
			rgce = rgce[1+consumed:]
		case 0x18:
			rgce = rgce[5:]
		case 0x19:
			etpg := rgce[0]
			rgce = rgce[1:]
			switch etpg {
			case 0x01, 0x02, 0x08, 0x20, 0x21:
				rgce = rgce[2:]
			case 0x04:
				n := int(u16(rgce[:2])) + 1
				rgce = rgce[2+2*n:]
			case 0x10:
				rgce = rgce[2:]
				if len(stack) == 0 {
					return "", errStackLen()
				}
				e := stack[len(stack)-1]
				s := f.splitOff(e)
				f.push("SUM(" + s + ")")
			case 0x40, 0x41:
				if len(stack) == 0 {
					return "", errStackLen()
				}
				e := stack[len(stack)-1]
				var space string
				switch rgce[0] {
				case 0x00, 0x02, 0x04, 0x06:
					space = " "
				case 0x01, 0x03, 0x05:
					space = "\r"
				default:
					return "", errors.New("Unrecognized PtgAttrSpaceType")
				}
				cch := int(rgce[1])
				for i := 0; i < cch; i++ {
					f.insert(e, space)
				}
				rgce = rgce[2:]
			default:
				return "", fmt.Errorf("Etpg(%d)", etpg)
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
				return "", errors.New("Unrecognized BErr")
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
			f.push("{PtgArray}")
			rgce = rgce[7:]
		case 0x21, 0x22, 0x41, 0x42, 0x61, 0x62:
			var iftab, argc int
			if ptg == 0x22 || ptg == 0x42 || ptg == 0x62 {
				iftab = int(u16(rgce[1:]))
				argc = int(rgce[0])
				rgce = rgce[3:]
			} else {
				iftab = int(u16(rgce))
				if iftab >= ftabLen {
					return "", fmt.Errorf("IfTab(%d)", iftab)
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
				if iftab >= ftabLen {
					return "", fmt.Errorf("IfTab(%d)", iftab)
				}
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
				if iftab >= ftabLen {
					return "", fmt.Errorf("IfTab(%d)", iftab)
				}
				f.push(ftab[iftab])
				f.push("()")
			}
		case 0x23, 0x43, 0x63:
			iname := int(u32(rgce)) - 1
			stack = append(stack, f.len())
			if iname >= 0 && iname < len(ctx.names) {
				f.push(ctx.names[iname].Name)
			} else {
				f.push("#REF!") // includes index 0, which wraps to usize::MAX in Rust
			}
			rgce = rgce[4:]
		case 0x24, 0x44, 0x64:
			stack = append(stack, f.len())
			if pre8 {
				raw := u16(rgce)
				row := (raw & 0x3FFF) + 1
				col := rgce[2]
				if raw&0x4000 == 0 {
					f.pushByte('$')
				}
				f.pushColumn(uint32(col))
				if raw&0x8000 == 0 {
					f.pushByte('$')
				}
				f.push(strconv.Itoa(int(row)))
				rgce = rgce[3:]
			} else {
				row := u16(rgce) + 1
				col := uint16(rgce[2]) | uint16(rgce[3]&0x3F)<<8
				if rgce[3]&0x80 != 0x80 {
					f.pushByte('$')
				}
				f.pushColumn(uint32(col))
				if rgce[3]&0x40 != 0x40 {
					f.pushByte('$')
				}
				f.push(strconv.Itoa(int(row)))
				rgce = rgce[4:]
			}
		case 0x25, 0x45, 0x65:
			stack = append(stack, f.len())
			if pre8 {
				rf := uint32(u16(rgce[0:2])&0x3FFF) + 1
				rl := uint32(u16(rgce[2:4])&0x3FFF) + 1
				cf := uint32(rgce[4])
				cl := uint32(rgce[5])
				f.pushByte('$')
				f.pushColumn(cf)
				f.push("$" + strconv.FormatUint(uint64(rf), 10) + ":$")
				f.pushColumn(cl)
				f.push("$" + strconv.FormatUint(uint64(rl), 10))
				rgce = rgce[6:]
			} else {
				cf := uint16(rgce[4]) | uint16(rgce[5]&0x3F)<<8
				cl := uint16(rgce[6]) | uint16(rgce[7]&0x3F)<<8
				rf := uint32(u16(rgce[0:2])) + 1
				rl := uint32(u16(rgce[2:4])) + 1
				if rgce[5]&0x80 != 0x80 {
					f.pushByte('$')
				}
				f.pushColumn(uint32(cf))
				if rgce[5]&0x40 != 0x40 {
					f.pushByte('$')
				}
				f.push(strconv.FormatUint(uint64(rf), 10) + ":")
				if rgce[7]&0x80 != 0x80 {
					f.pushByte('$')
				}
				f.pushColumn(uint32(cl))
				if rgce[7]&0x40 != 0x40 {
					f.pushByte('$')
				}
				f.push(strconv.FormatUint(uint64(rl), 10))
				rgce = rgce[8:]
			}
		case 0x2A, 0x4A, 0x6A:
			stack = append(stack, f.len())
			f.push("#REF!")
			if pre8 {
				rgce = rgce[3:]
			} else {
				rgce = rgce[4:]
			}
		case 0x2B, 0x4B, 0x6B:
			stack = append(stack, f.len())
			f.push("#REF!")
			if pre8 {
				rgce = rgce[6:]
			} else {
				rgce = rgce[8:]
			}
		case 0x39, 0x59:
			stack = append(stack, f.len())
			f.push("[PtgNameX]")
			rgce = rgce[6:]
		default:
			return "", fmt.Errorf("Unrecognized ptg %d", ptg)
		}
	}
	if len(stack) == 1 {
		return string(f.b), nil
	}
	return "", fmt.Errorf("InvalidFormula { stack_size: %d }", len(stack))
}

var binOps = map[byte]string{
	0x03: "+", 0x04: "-", 0x05: "*", 0x06: "/", 0x07: "^", 0x08: "&", 0x09: "<", 0x0A: "<=",
	0x0B: "=", 0x0C: ">", 0x0D: ">=", 0x0E: "<>", 0x0F: " ", 0x10: ",", 0x11: ":",
}

func parseFormulaValue(r []byte, format *cellFormat, is1904 bool) (Data, bool, error) {
	if r[6] == 0xFF && r[7] == 0xFF {
		switch r[0] {
		case 0x00:
			return Data{}, false, nil
		case 0x01:
			return Data{Kind: Bool, B: r[2] != 0}, true, nil
		case 0x02:
			d, err := parseErr(r[2])
			return d, err == nil, err
		case 0x03:
			return Data{Kind: String, S: ""}, true, nil
		}
		return Data{}, false, errors.New("unrecognized formula value")
	}
	return formatExcelF64(f64le(r), format, is1904), true, nil
}
