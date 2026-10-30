package calamine

// Office Open XML (.xlsx/.xlsm) reader (port of calamine src/xlsx/mod.rs and cells_reader.rs).

import (
	"archive/zip"
	"bytes"
	"errors"
	"fmt"
	"io"
	"math"
	"strconv"
	"strings"
	"unicode/utf8"
)

const (
	maxRows    = 1_048_576
	maxColumns = 16_384
)

// zipPkg wraps a zip archive with calamine's case-insensitive path cache.
type zipPkg struct {
	zr     *zip.Reader
	byName map[string]*zip.File
	cache  map[string]string
}

func openZip(data []byte) (*zipPkg, error) {
	zr, err := zip.NewReader(bytes.NewReader(data), int64(len(data)))
	if err != nil {
		return nil, err
	}
	z := &zipPkg{zr: zr, byName: map[string]*zip.File{}, cache: map[string]string{}}
	for _, f := range zr.File {
		if _, ok := z.byName[f.Name]; !ok {
			z.byName[f.Name] = f
		}
		norm := strings.ToLower(strings.ReplaceAll(f.Name, "\\", "/"))
		z.cache[norm] = f.Name
	}
	return z, nil
}

func asciiLower(s string) string {
	b := []byte(s)
	for i, c := range b {
		if c >= 'A' && c <= 'Z' {
			b[i] = c + 32
		}
	}
	return string(b)
}

func (z *zipPkg) cachedPath(p string) string {
	if v, ok := z.cache[asciiLower(p)]; ok {
		return v
	}
	return p
}

var errZipNotFound = errors.New("file not found in archive")

// read returns the bytes of an entry, or errZipNotFound.
func (z *zipPkg) read(path string) ([]byte, error) {
	name := z.cachedPath(path)
	f, ok := z.byName[name]
	if !ok {
		return nil, errZipNotFound
	}
	rc, err := f.Open()
	if err != nil {
		return nil, err
	}
	defer rc.Close()
	return io.ReadAll(rc)
}

func (z *zipPkg) xml(path string) (*xmlReader, error) {
	b, err := z.read(path)
	if err != nil {
		return nil, err
	}
	return newXMLReader(b), nil
}

func isEncryptedCfb(data []byte) bool {
	r := &fileReader{buf: data}
	c, err := func() (c *cfb, err error) {
		defer func() {
			if p := recover(); p != nil {
				err = fmt.Errorf("%v", p)
			}
		}()
		return newCfb(r, len(data))
	}()
	return err == nil && c.hasDirectory("EncryptedPackage")
}

type xlsxSheet struct{ name, path string }

// Xlsx is an opened xlsx workbook.
type Xlsx struct {
	z        *zipPkg
	xlPath   string
	strings  []string
	sheets   []xlsxSheet
	formats  []cellFormat
	is1904   bool
	meta     []Sheet
	names    []Name
	pictures []Picture
}

func (x *Xlsx) Format() string       { return "xlsx" }
func (x *Xlsx) Sheets() []Sheet      { return x.meta }
func (x *Xlsx) DefinedNames() []Name { return x.names }

// OpenXlsx opens an xlsx/xlsm package held in memory.
func OpenXlsx(data []byte) (wb Workbook, err error) {
	defer func() {
		if p := recover(); p != nil {
			wb, err = nil, fmt.Errorf("xlsx: malformed file (%v)", p)
		}
	}()
	if isEncryptedCfb(data) {
		return nil, errors.New("workbook is password protected")
	}
	z, err := openZip(data)
	if err != nil {
		return nil, err
	}
	x := &Xlsx{z: z, xlPath: "xl/"}
	if err := x.readPackageRelationships(); err != nil {
		return nil, err
	}
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
	if err := x.readPictures(); err != nil {
		return nil, err
	}
	return x, nil
}

func eofErr(what string) error { return errors.New("unexpected end of xml: " + what) }

func (x *Xlsx) readPackageRelationships() error {
	xr, err := x.z.xml("_rels/.rels")
	if err != nil {
		if err == errZipNotFound {
			return errors.New("file not found: _rels/.rels")
		}
		return err
	}
	for {
		ev, err := xr.next()
		if err != nil {
			return err
		}
		if ev.kind == evStart && ev.isLocal("Relationships") {
			break
		}
		if ev.kind == evEOF {
			return eofErr("Relationships")
		}
	}
	var target *string
	for {
		ev, err := xr.next()
		if err != nil {
			return err
		}
		if ev.kind == evStart && ev.isLocal("Relationship") {
			v, has, err := getAttrs(ev.attrs, "Type", "Target")
			if err != nil {
				return err
			}
			if has[0] && strings.HasSuffix(v[0], "/relationships/officeDocument") && has[1] {
				t, err := decodeAttr(v[1])
				if err != nil {
					return err
				}
				target = &t
			}
		} else if ev.kind == evEnd && ev.isLocal("Relationships") {
			break
		} else if ev.kind == evEOF {
			return eofErr("Relationships")
		}
	}
	if target == nil {
		return errors.New("relationship not found")
	}
	t := *target
	if i := strings.LastIndexByte(t, '/'); i >= 0 {
		p := t[:i+1]
		x.xlPath = strings.TrimPrefix(p, "/")
	} else {
		x.xlPath = ""
	}
	return nil
}

func (x *Xlsx) readSharedStrings() error {
	xr, err := x.z.xml(x.xlPath + "sharedStrings.xml")
	if err == errZipNotFound {
		return nil
	} else if err != nil {
		return err
	}
	for {
		ev, err := xr.next()
		if err != nil {
			return err
		}
		if ev.kind == evStart && ev.isLocal("sst") {
			if _, _, err := rawAttrLookup(ev.attrs, "uniqueCount"); err != nil {
				return err
			}
			break
		}
		if ev.kind == evEOF {
			return eofErr("sst")
		}
	}
	for {
		ev, err := xr.next()
		if err != nil {
			return err
		}
		switch {
		case ev.kind == evStart && ev.isLocal("si"):
			s, ok, err := readStringWithBufs(xr, ev.name)
			if err != nil {
				return err
			}
			if ok {
				x.strings = append(x.strings, s)
			}
		case ev.kind == evEnd && ev.isLocal("sst"):
			return nil
		case ev.kind == evEOF:
			return eofErr("sst")
		}
	}
}

func (x *Xlsx) readStyles() error {
	xr, err := x.z.xml(x.xlPath + "styles.xml")
	if err == errZipNotFound {
		return nil
	} else if err != nil {
		return err
	}
	numFmts := map[string]string{}
	for {
		ev, err := xr.next()
		if err != nil {
			return err
		}
		switch {
		case ev.kind == evStart && ev.isLocal("numFmts"):
			for {
				in, err := xr.next()
				if err != nil {
					return err
				}
				if in.kind == evStart && in.isLocal("numFmt") {
					v, has, err := getAttrs(in.attrs, "numFmtId", "formatCode")
					if err != nil {
						return err
					}
					if has[0] && has[1] {
						f, err := decodeAttr(v[1])
						if err != nil {
							return err
						}
						numFmts[v[0]] = f
					}
				} else if in.kind == evEnd && in.isLocal("numFmts") {
					break
				} else if in.kind == evEOF {
					return eofErr("numFmts")
				}
			}
		case ev.kind == evStart && ev.isLocal("cellXfs"):
			for {
				in, err := xr.next()
				if err != nil {
					return err
				}
				if in.kind == evStart && in.isLocal("xf") {
					id, ok, err := rawAttrLookup(in.attrs, "numFmtId")
					if err != nil {
						return err
					}
					f := fmtOther
					if ok {
						if code, ok := numFmts[id]; ok {
							f = detectCustomNumberFormat(code)
						} else {
							f = builtinFormatByID(id)
						}
					}
					x.formats = append(x.formats, f)
				} else if in.kind == evEnd && in.isLocal("cellXfs") {
					break
				} else if in.kind == evEOF {
					return eofErr("cellXfs")
				}
			}
		case ev.kind == evEnd && ev.isLocal("styleSheet"):
			return nil
		case ev.kind == evEOF:
			return eofErr("styleSheet")
		}
	}
}

type xlsxRel struct{ target, typ string }

func (x *Xlsx) readRelationships() (map[string]xlsxRel, error) {
	p := x.xlPath + "_rels/workbook.xml.rels"
	xr, err := x.z.xml(p)
	if err == errZipNotFound {
		return nil, errors.New("file not found: " + p)
	} else if err != nil {
		return nil, err
	}
	rels := map[string]xlsxRel{}
	for {
		ev, err := xr.next()
		if err != nil {
			return nil, err
		}
		switch {
		case ev.kind == evStart && ev.isLocal("Relationship"):
			v, has, err := getAttrs(ev.attrs, "Id", "Type", "Target")
			if err != nil {
				return nil, err
			}
			if has[0] {
				rels[v[0]] = xlsxRel{target: v[2], typ: v[1]}
			}
		case ev.kind == evEnd && ev.isLocal("Relationships"):
			return rels, nil
		case ev.kind == evEOF:
			return nil, eofErr("Relationships")
		}
	}
}

func (x *Xlsx) readWorkbook(rels map[string]xlsxRel) error {
	xr, err := x.z.xml(x.xlPath + "workbook.xml")
	if err == errZipNotFound {
		return nil
	} else if err != nil {
		return err
	}
	var names []Name
	for {
		ev, err := xr.next()
		if err != nil {
			return err
		}
		switch {
		case ev.kind == evStart && ev.isLocal("sheet"):
			name := ""
			relID := ""
			vis := Visible
			var aerr error
			ierr := iterAttrs(ev.attrs, func(k, v string) bool {
				switch {
				case k == "name":
					name, aerr = decodeAttr(v)
				case k == "state":
					switch v {
					case "visible":
						vis = Visible
					case "hidden":
						vis = Hidden
					case "veryHidden":
						vis = VeryHidden
					default:
						aerr = errors.New("unrecognized sheet:state " + v)
					}
				case localNameMatches(k, "id"):
					relID = v
				}
				return aerr == nil
			})
			if aerr != nil {
				return aerr
			}
			if ierr != nil {
				return ierr
			}
			rel, ok := rels[relID]
			if !ok {
				return errors.New("relationship not found")
			}
			var path string
			if strings.HasPrefix(rel.target, "/") {
				path = rel.target[1:]
			} else {
				path = x.xlPath + rel.target
			}
			last := rel.typ
			if i := strings.LastIndexByte(last, '/'); i >= 0 {
				last = last[i+1:]
			}
			var typ SheetType
			switch last {
			case "worksheet":
				typ = WorkSheet
			case "chartsheet":
				typ = ChartSheet
			case "dialogsheet":
				typ = DialogSheet
			default:
				return errors.New("unrecognized sheet type " + path)
			}
			x.meta = append(x.meta, Sheet{Name: name, Type: typ, Visible: vis})
			x.sheets = append(x.sheets, xlsxSheet{name, path})
		case ev.kind == evStart && ev.isLocal("workbookPr"):
			v, ok, err := rawAttrLookup(ev.attrs, "date1904")
			if err != nil {
				return err
			}
			if ok {
				x.is1904 = v == "1" || v == "true"
			}
		case ev.kind == evStart && ev.isLocal("definedName"):
			v, ok, err := rawAttrLookup(ev.attrs, "name")
			if err != nil {
				return err
			}
			if ok {
				name, err := decodeAttr(v)
				if err != nil {
					return err
				}
				var sb strings.Builder
				for {
					in, err := xr.next()
					if err != nil {
						return err
					}
					if in.kind == evText {
						t, err := xml10Content(in.text)
						if err != nil {
							return err
						}
						sb.WriteString(t)
					} else if in.kind == evRef {
						if err := unescapeRef(in.text, &sb); err != nil {
							return err
						}
					} else if in.kind == evEnd && bytes.Equal(in.name, ev.name) {
						break
					} else if in.kind == evEOF {
						return eofErr("workbook")
					}
				}
				names = append(names, Name{name, sb.String()})
			}
		case ev.kind == evEnd && ev.isLocal("workbook"):
			x.names = names
			return nil
		case ev.kind == evEOF:
			return eofErr("workbook")
		}
	}
}

// ---- references ----

func getRowAndOptionalColumn(s string) (uint32, uint32, bool, error) {
	var col, row uint32
	i := 0
	n := len(s)
	for i < n {
		c := s[i]
		switch {
		case c >= 'A' && c <= 'Z':
			col = col*26 + uint32(c-'A') + 1
		case c >= 'a' && c <= 'z':
			col = col*26 + uint32(c-'a') + 1
		case c >= '0' && c <= '9':
			row = uint32(c - '0')
			i++
			goto rows
		default:
			return 0, 0, false, errors.New("invalid character in cell reference")
		}
		i++
	}
rows:
	for i < n {
		c := s[i]
		if c >= '0' && c <= '9' {
			row = row*10 + uint32(c-'0')
		} else {
			return 0, 0, false, errors.New("invalid character in cell reference")
		}
		i++
	}
	if row == 0 {
		return 0, 0, false, errors.New("range without row component")
	}
	if col == 0 {
		return row - 1, 0, false, nil
	}
	return row - 1, col - 1, true, nil
}

func getRowColumn(s string) (uint32, uint32, error) {
	r, c, ok, err := getRowAndOptionalColumn(s)
	if err != nil {
		return 0, 0, err
	}
	if !ok {
		return 0, 0, errors.New("range without column component")
	}
	return r, c, nil
}

func getRow(s string) (uint32, error) {
	r, _, _, err := getRowAndOptionalColumn(s)
	return r, err
}

func getDimension(s string) (Dimensions, error) {
	parts := strings.Split(s, ":")
	var pr, pc []uint32
	for _, p := range parts {
		r, c, err := getRowColumn(p)
		if err != nil {
			return Dimensions{}, err
		}
		pr = append(pr, r)
		pc = append(pc, c)
	}
	switch len(parts) {
	case 1:
		return Dimensions{pr[0], pc[0], pr[0], pc[0]}, nil
	case 2:
		return Dimensions{pr[0], pc[0], pr[1], pc[1]}, nil
	}
	return Dimensions{}, errors.New("invalid dimension count")
}

// ---- strings ----

// unescapeXMLEscapes decodes Excel's _x00HH_ escapes.
func unescapeXMLEscapes(s string) string {
	if !strings.Contains(s, "_x00") {
		return s
	}
	b := []byte(s)
	var out strings.Builder
	i := 0
	for i < len(b) {
		if i+7 <= len(b) && b[i] == '_' && string(b[i:i+4]) == "_x00" && b[i+6] == '_' {
			if v, ok := parseHexU8(b[i+4 : i+6]); ok {
				out.WriteRune(rune(v))
				i += 7
				continue
			}
		}
		// copy one UTF-8 character
		_, size := utf8.DecodeRuneInString(s[i:])
		out.WriteString(s[i : i+size])
		i += size
	}
	return out.String()
}

func hexVal(c byte) (byte, bool) {
	switch {
	case c >= '0' && c <= '9':
		return c - '0', true
	case c >= 'a' && c <= 'f':
		return c - 'a' + 10, true
	case c >= 'A' && c <= 'F':
		return c - 'A' + 10, true
	}
	return 0, false
}

// parseHexU8 is u8::from_str_radix(s, 16) on a two-byte string (a leading '+' is allowed).
func parseHexU8(b []byte) (byte, bool) {
	if b[0] == '+' {
		v, ok := hexVal(b[1])
		return v, ok
	}
	h, ok1 := hexVal(b[0])
	l, ok2 := hexVal(b[1])
	if !ok1 || !ok2 {
		return 0, false
	}
	return h<<4 | l, true
}

func trimXMLWS(s string) string {
	return strings.Trim(s, " \t\r\n")
}

// readStringWithBufs reads <si>/<is> content: plain and rich text, skipping phonetic runs.
func readStringWithBufs(xr *xmlReader, closing []byte) (string, bool, error) {
	var rich *strings.Builder
	phonetic := false
	for {
		ev, err := xr.next()
		if err != nil {
			return "", false, err
		}
		switch {
		case ev.kind == evStart && ev.isLocal("r") && rich == nil:
			rich = &strings.Builder{}
		case ev.kind == evStart && ev.isLocal("rPh"):
			phonetic = true
		case ev.kind == evEnd && bytes.Equal(ev.name, closing):
			if rich == nil {
				return "", true, nil
			}
			return rich.String(), true, nil
		case ev.kind == evEnd && ev.isLocal("rPh"):
			phonetic = false
		case ev.kind == evStart && ev.isLocal("t") && !phonetic:
			sp, ok, err := rawAttrLookup(ev.attrs, "xml:space")
			if err != nil {
				return "", false, err
			}
			preserve := ok && sp == "preserve"
			var sb strings.Builder
			for {
				in, err := xr.next()
				if err != nil {
					return "", false, err
				}
				if in.kind == evText || in.kind == evCData {
					t, err := xml10Content(in.text)
					if err != nil {
						return "", false, err
					}
					sb.WriteString(t)
				} else if in.kind == evRef {
					if err := unescapeRef(in.text, &sb); err != nil {
						return "", false, err
					}
				} else if in.kind == evEnd && bytes.Equal(in.name, ev.name) {
					break
				} else if in.kind == evEOF {
					return "", false, eofErr("t")
				}
			}
			v := sb.String()
			if preserve {
				v = unescapeXMLEscapes(v)
			} else {
				v = unescapeXMLEscapes(trimXMLWS(v))
			}
			if rich != nil {
				rich.WriteString(v)
			} else {
				rich = &strings.Builder{}
				rich.WriteString(v)
			}
		case ev.kind == evEOF:
			return "", false, eofErr("")
		}
	}
}

// ---- cells ----

type sharedFormula struct {
	formula string
	start   [2]uint32
	set     bool
}

type xlsxCellReader struct {
	x        *Xlsx
	xr       *xmlReader
	row, col uint32
	formulas []sharedFormula
}

var errNotAWorksheet = errors.New("not a worksheet")

func (x *Xlsx) cellReader(name string) (*xlsxCellReader, error) {
	var path string
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
	xr, err := x.z.xml(path)
	if err == errZipNotFound {
		return nil, fmt.Errorf("worksheet %q not found", name)
	} else if err != nil {
		return nil, err
	}
	shType := ""
	for {
		ev, err := xr.next()
		if err != nil {
			return nil, err
		}
		if ev.kind == evStart {
			ln := string(ev.localName())
			if ln == "dimension" {
				v, ok, err := rawAttrLookup(ev.attrs, "ref")
				if err != nil {
					return nil, err
				}
				if !ok {
					return nil, errors.New("unexpected node dimension")
				}
				if _, err := getDimension(v); err != nil {
					return nil, err
				}
				continue
			}
			if ln == "sheetData" {
				break
			}
			if shType == "" {
				shType = ln
			}
		} else if ev.kind == evEOF {
			if shType != "" {
				return nil, errNotAWorksheet
			}
			return nil, eofErr("worksheet")
		}
	}
	return &xlsxCellReader{x: x, xr: xr}, nil
}

// atoiUsize mimics atoi_simd::parse::<usize, SKIP_ZEROES=true, SKIP_PLUS=false>; ok=false on failure.
// Values that fit in u64 but not in int are returned as math.MaxInt (never a valid index).
func atoiUsize(s string) (int, bool) {
	if s == "" {
		return 0, false
	}
	var v uint64
	for i := 0; i < len(s); i++ {
		c := s[i]
		if c < '0' || c > '9' {
			return 0, false
		}
		d := uint64(c - '0')
		if v > (math.MaxUint64-d)/10 {
			return 0, false
		}
		v = v*10 + d
	}
	if v > math.MaxInt {
		return math.MaxInt, true
	}
	return int(v), true
}

// parseFastFloat accepts what fast_float2::parse accepts for a whole string.
func parseFastFloat(s string) (float64, bool) {
	t := s
	if len(t) > 0 && (t[0] == '+' || t[0] == '-') {
		t = t[1:]
	}
	lt := strings.ToLower(t)
	if lt == "inf" || lt == "infinity" || lt == "nan" {
		v, _ := strconv.ParseFloat(s, 64)
		if lt == "nan" {
			return math.NaN(), true
		}
		return v, true
	}
	i := 0
	digits := 0
	for i < len(t) && t[i] >= '0' && t[i] <= '9' {
		i++
		digits++
	}
	if i < len(t) && t[i] == '.' {
		i++
		for i < len(t) && t[i] >= '0' && t[i] <= '9' {
			i++
			digits++
		}
	}
	if digits == 0 {
		return 0, false
	}
	if i < len(t) && (t[i] == 'e' || t[i] == 'E') {
		i++
		if i < len(t) && (t[i] == '+' || t[i] == '-') {
			i++
		}
		ed := 0
		for i < len(t) && t[i] >= '0' && t[i] <= '9' {
			i++
			ed++
		}
		if ed == 0 {
			return 0, false
		}
	}
	if i != len(t) {
		return 0, false
	}
	v, err := strconv.ParseFloat(s, 64)
	if err != nil {
		if ne, ok := err.(*strconv.NumError); ok && ne.Err == strconv.ErrRange {
			return v, true
		}
		return 0, false
	}
	return v, true
}

func parseCellError(s string) (CellErrorType, error) {
	switch s {
	case "#DIV/0!":
		return ErrDiv0, nil
	case "#N/A":
		return ErrNA, nil
	case "#NAME?":
		return ErrName, nil
	case "#NULL!":
		return ErrNull, nil
	case "#NUM!":
		return ErrNum, nil
	case "#REF!":
		return ErrRef, nil
	case "#VALUE!":
		return ErrValue, nil
	}
	return 0, errors.New("unsupported cell error value " + s)
}

func readBool(v string) (Data, error) {
	t := strings.TrimSpace(v)
	switch {
	case t == "":
		return Data{}, nil
	case t == "0" || strings.EqualFold(t, "false"):
		return Data{Kind: Bool, B: false}, nil
	case t == "1" || strings.EqualFold(t, "true"):
		return Data{Kind: Bool, B: true}, nil
	}
	return Data{}, errors.New("unrecognized boolean cell value " + v)
}

func (x *Xlsx) readV(v string, style string, hasStyle bool, typ string, hasType bool) (Data, error) {
	var cf *cellFormat
	other := fmtOther
	if hasStyle {
		id, ok := atoiUsize(style)
		if !ok {
			id = 0
		}
		cf = fmtAt(x.formats, id)
	} else {
		cf = &other
	}
	if !hasType {
		typ = ""
	}
	switch {
	case hasType && typ == "s":
		if v == "" {
			return Data{}, nil
		}
		idx, ok := atoiUsize(v)
		if !ok {
			idx = 0
		}
		if idx < len(x.strings) {
			return Data{Kind: String, S: x.strings[idx]}, nil
		}
		return Data{}, errors.New("cell string index not found in shared strings table")
	case hasType && typ == "b":
		return readBool(v)
	case hasType && typ == "d":
		return Data{Kind: DateTimeIso, S: v}, nil
	case hasType && typ == "e":
		e, err := parseCellError(v)
		if err != nil {
			return Data{}, err
		}
		return Data{Kind: Error, E: e}, nil
	case hasType && typ == "str":
		return Data{Kind: String, S: unescapeXMLEscapes(v)}, nil
	case !hasType || typ == "n":
		if v == "" {
			return Data{}, nil
		}
		if f, ok := parseFastFloat(v); ok {
			return formatExcelF64(f, cf, x.is1904), nil
		}
		if !hasType {
			return Data{Kind: String, S: v}, nil
		}
		return Data{}, errors.New("invalid float " + v)
	}
	return Data{}, errors.New("unsupported cell type " + typ)
}

func (cr *xlsxCellReader) readValue(e xmlEvent, style string, hasStyle bool, typ string, hasType bool) (Data, error) {
	xr := cr.xr
	switch string(e.localName()) {
	case "is":
		s, ok, err := readStringWithBufs(xr, e.name)
		if err != nil {
			return Data{}, err
		}
		if !ok {
			return Data{}, nil
		}
		return Data{Kind: String, S: s}, nil
	case "v":
		if hasType && (typ == "inlineStr" || typ == "is") {
			return Data{}, xr.readToEnd(e.name)
		}
		if !hasType || typ == "n" || typ == "s" || typ == "b" || typ == "e" {
			ev, err := xr.next()
			if err != nil {
				return Data{}, err
			}
			var val Data
			switch {
			case ev.kind == evText:
				val, err = cr.x.readV(string(ev.text), style, hasStyle, typ, hasType)
				if err != nil {
					return Data{}, err
				}
			case ev.kind == evEnd && bytes.Equal(ev.name, e.name):
				return Data{}, nil
			case ev.kind == evEOF:
				return Data{}, eofErr("v")
			}
			if err := xr.readToEnd(e.name); err != nil {
				return Data{}, err
			}
			return val, nil
		}
		var sb strings.Builder
		for {
			ev, err := xr.next()
			if err != nil {
				return Data{}, err
			}
			if ev.kind == evText {
				t, err := xml10Content(ev.text)
				if err != nil {
					return Data{}, err
				}
				sb.WriteString(t)
			} else if ev.kind == evRef {
				if err := unescapeRef(ev.text, &sb); err != nil {
					return Data{}, err
				}
			} else if ev.kind == evEnd && bytes.Equal(ev.name, e.name) {
				break
			} else if ev.kind == evEOF {
				return Data{}, eofErr("v")
			}
		}
		return cr.x.readV(sb.String(), style, hasStyle, typ, hasType)
	case "f":
		return Data{}, xr.readToEnd(e.name)
	}
	return Data{}, errors.New("unexpected node: v, f, or is")
}

// nextCell returns ok=false at the end of sheetData.
func (cr *xlsxCellReader) nextCell() (Cell, bool, error) {
	xr := cr.xr
	for {
		ev, err := xr.next()
		if err != nil {
			return Cell{}, false, err
		}
		switch {
		case ev.kind == evStart && ev.isLocal("row"):
			v, ok, err := rawAttrLookup(ev.attrs, "r")
			if err != nil {
				return Cell{}, false, err
			}
			if ok {
				r, err := getRow(v)
				if err != nil {
					return Cell{}, false, err
				}
				cr.row = r
			}
		case ev.kind == evEnd && ev.isLocal("row"):
			cr.row++
			cr.col = 0
		case ev.kind == evStart && ev.isLocal("c"):
			v, has, err := getAttrs(ev.attrs, "r", "s", "t")
			if err != nil {
				return Cell{}, false, err
			}
			row, col := cr.row, cr.col
			if has[0] {
				r, c, err := getRowColumn(v[0])
				if err != nil {
					return Cell{}, false, err
				}
				cr.col = c
				row, col = r, c
			}
			var value Data
			for {
				in, err := xr.next()
				if err != nil {
					return Cell{}, false, err
				}
				if in.kind == evStart {
					value, err = cr.readValue(in, v[1], has[1], v[2], has[2])
					if err != nil {
						return Cell{}, false, err
					}
				} else if in.kind == evEnd && in.isLocal("c") {
					break
				} else if in.kind == evEOF {
					return Cell{}, false, eofErr("c")
				}
			}
			cr.col++
			return Cell{row, col, value}, true, nil
		case ev.kind == evEnd && ev.isLocal("sheetData"):
			return Cell{}, false, nil
		case ev.kind == evEOF:
			return Cell{}, false, eofErr("sheetData")
		}
	}
}

// readFormulaRecord returns the formula text for one element inside <c> (has=false when none).
func (cr *xlsxCellReader) readFormulaRecord(e xmlEvent, row, col uint32) (string, bool, error) {
	xr := cr.xr
	var formula string
	hasFormula := false
	switch string(e.localName()) {
	case "is", "v":
		if err := xr.readToEnd(e.name); err != nil {
			return "", false, err
		}
	case "f":
		var sb strings.Builder
		for {
			ev, err := xr.next()
			if err != nil {
				return "", false, err
			}
			if ev.kind == evText {
				t, err := xml10Content(ev.text)
				if err != nil {
					return "", false, err
				}
				sb.WriteString(t)
			} else if ev.kind == evRef {
				if err := unescapeRef(ev.text, &sb); err != nil {
					return "", false, err
				}
			} else if ev.kind == evEnd && bytes.Equal(ev.name, e.name) {
				break
			} else if ev.kind == evEOF {
				return "", false, eofErr("f")
			}
		}
		formula, hasFormula = sb.String(), true
	default:
		return "", false, errors.New("unexpected node: v, f, or is")
	}
	v, has, err := getAttrs(e.attrs, "t", "si", "ref")
	if err != nil {
		return "", false, err
	}
	if has[0] && v[0] == "shared" {
		if !has[1] {
			return "", false, errors.New("si attribute is mandatory if it is shared")
		}
		si, ok := atoiUsize(v[1])
		if !ok {
			return "", false, errors.New("si attribute must be a number")
		}
		if has[2] {
			d, err := getDimension(v[2])
			if err != nil {
				return "", false, err
			}
			if len(cr.formulas) <= si {
				nf := make([]sharedFormula, si+1)
				copy(nf, cr.formulas)
				cr.formulas = nf
			}
			cr.formulas[si] = sharedFormula{formula: formula, start: [2]uint32{d.StartRow, d.StartCol}, set: true}
			return formula, true, nil
		}
		if si < len(cr.formulas) && cr.formulas[si].set {
			t := cr.formulas[si]
			out, err := expandSharedFormula(t.formula, t.start, [2]uint32{row, col})
			if err != nil {
				return "", false, err
			}
			return out, true, nil
		}
		return "", false, nil
	}
	return formula, hasFormula, nil
}

func (cr *xlsxCellReader) nextFormula() (FCell, bool, error) {
	xr := cr.xr
	for {
		ev, err := xr.next()
		if err != nil {
			return FCell{}, false, err
		}
		switch {
		case ev.kind == evStart && ev.isLocal("row"):
			v, ok, err := rawAttrLookup(ev.attrs, "r")
			if err != nil {
				return FCell{}, false, err
			}
			if ok {
				r, err := getRow(v)
				if err != nil {
					return FCell{}, false, err
				}
				cr.row = r
			}
		case ev.kind == evEnd && ev.isLocal("row"):
			cr.row++
			cr.col = 0
		case ev.kind == evStart && ev.isLocal("c"):
			v, ok, err := rawAttrLookup(ev.attrs, "r")
			if err != nil {
				return FCell{}, false, err
			}
			row, col := cr.row, cr.col
			if ok {
				r, c, err := getRowColumn(v)
				if err != nil {
					return FCell{}, false, err
				}
				cr.col = c
				row, col = r, c
			}
			value := ""
			for {
				in, err := xr.next()
				if err != nil {
					return FCell{}, false, err
				}
				if in.kind == evStart {
					f, has, err := cr.readFormulaRecord(in, row, col)
					if err != nil {
						return FCell{}, false, err
					}
					if has {
						value = f
					}
				} else if in.kind == evEnd && in.isLocal("c") {
					break
				} else if in.kind == evEOF {
					return FCell{}, false, eofErr("c")
				}
			}
			cr.col++
			return FCell{row, col, value}, true, nil
		case ev.kind == evEnd && ev.isLocal("sheetData"):
			return FCell{}, false, nil
		case ev.kind == evEOF:
			return FCell{}, false, eofErr("sheetData")
		}
	}
}

func (x *Xlsx) WorksheetRange(name string) (Range, error) {
	cr, err := x.cellReader(name)
	if err == errNotAWorksheet {
		return Range{}, nil
	} else if err != nil {
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

func (x *Xlsx) WorksheetFormula(name string) (FRange, error) {
	cr, err := x.cellReader(name)
	if err == errNotAWorksheet {
		return FRange{}, nil
	} else if err != nil {
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

func (x *Xlsx) MergedCells(name string) ([]Dimensions, bool, error) {
	var path string
	found := false
	for _, s := range x.sheets {
		if s.name == name {
			path, found = s.path, true
			break
		}
	}
	if !found {
		return nil, true, fmt.Errorf("worksheet %q not found", name)
	}
	xr, err := x.z.xml(path)
	if err == errZipNotFound {
		return nil, true, fmt.Errorf("worksheet %q not found", name)
	} else if err != nil {
		return nil, true, err
	}
	var merged []Dimensions
	for {
		ev, err := xr.next()
		if err != nil {
			return nil, true, err
		}
		if ev.kind == evStart && ev.isLocal("mergeCells") {
			for {
				in, err := xr.next()
				if err != nil {
					return nil, true, err
				}
				if in.kind == evStart && in.isLocal("mergeCell") {
					v, ok, err := rawAttrLookup(in.attrs, "ref")
					if err != nil {
						return nil, true, err
					}
					if ok {
						d, err := getDimension(v)
						if err != nil {
							return nil, true, err
						}
						merged = append(merged, d)
					}
				} else if in.kind == evEnd && in.isLocal("mergeCells") {
					break
				} else if in.kind == evEOF {
					return nil, true, eofErr("")
				}
			}
			return merged, true, nil
		}
		if ev.kind == evEOF {
			return merged, true, nil
		}
	}
}

// ---- shared formula expansion ----

type refKind int

const (
	refCell refKind = iota
	refRow
	refCol
)

type reference struct {
	kind           refKind
	row, col       uint32
	absRow, absCol bool
}

func (r reference) validate() error {
	switch r.kind {
	case refCell:
		if r.col >= maxColumns {
			return errors.New("column overflow")
		}
		if r.row >= maxRows {
			return errors.New("row overflow")
		}
	case refCol:
		if r.col >= maxColumns {
			return errors.New("column overflow")
		}
	case refRow:
		if r.row >= maxRows {
			return errors.New("row overflow")
		}
	}
	return nil
}

func isASCIILetter(c byte) bool { return (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') }
func isASCIIDigit(c byte) bool  { return c >= '0' && c <= '9' }

func parseReference(name []byte) (reference, error) {
	var col, row uint32
	absCol, absRow := false, false
	bad := errors.New("invalid reference")
	for i := 0; i < len(name); i++ {
		c := name[i]
		var peek byte
		hasPeek := i+1 < len(name)
		if hasPeek {
			peek = name[i+1]
		}
		switch {
		case c == '$' && hasPeek && isASCIILetter(peek):
			if row > 0 || col > 0 {
				return reference{}, bad
			}
			absCol = true
		case c == '$' && hasPeek && isASCIIDigit(peek):
			if row > 0 {
				return reference{}, bad
			}
			absRow = true
		case c == '$':
			return reference{}, bad
		case isASCIILetter(c):
			if row > 0 {
				return reference{}, bad
			}
			u := c
			if u >= 'a' {
				u -= 32
			}
			col = col*26 + uint32(u-'A') + 1
		case isASCIIDigit(c):
			row = row*10 + uint32(c-'0')
		default:
			return reference{}, bad
		}
	}
	var r reference
	switch {
	case col > 0 && row > 0:
		r = reference{kind: refCell, row: row - 1, col: col - 1, absRow: absRow, absCol: absCol}
	case col > 0:
		r = reference{kind: refCol, col: col - 1, absCol: absCol}
	case row > 0:
		r = reference{kind: refRow, row: row - 1, absRow: absRow}
	default:
		return reference{}, errors.New("empty reference")
	}
	return r, r.validate()
}

func (r reference) offset(dr, dc int64) (reference, error) {
	out := r
	switch r.kind {
	case refCell:
		if !r.absCol {
			out.col = uint32(int64(r.col) + dc)
		}
		if !r.absRow {
			out.row = uint32(int64(r.row) + dr)
		}
	case refCol:
		if !r.absCol {
			out.col = uint32(int64(r.col) + dc)
		}
	case refRow:
		if !r.absRow {
			out.row = uint32(int64(r.row) + dr)
		}
	}
	return out, out.validate()
}

func (r reference) format(sb *strings.Builder) {
	switch r.kind {
	case refCell:
		if r.absCol {
			sb.WriteByte('$')
		}
		pushColumn(r.col, sb)
		if r.absRow {
			sb.WriteByte('$')
		}
		sb.WriteString(strconv.FormatUint(uint64(r.row)+1, 10))
	case refCol:
		if r.absCol {
			sb.WriteByte('$')
		}
		pushColumn(r.col, sb)
	case refRow:
		if r.absRow {
			sb.WriteByte('$')
		}
		sb.WriteString(strconv.FormatUint(uint64(r.row)+1, 10))
	}
}

func offsetRange(rng []byte, dr, dc int64) (string, error) {
	idx := bytes.IndexByte(rng, ':')
	var sb strings.Builder
	if idx < 0 {
		r, err := parseReference(rng)
		if err != nil {
			return "", err
		}
		if r.kind != refCell {
			return "", errors.New("single reference type must be cell")
		}
		o, err := r.offset(dr, dc)
		if err != nil {
			return "", err
		}
		o.format(&sb)
		return sb.String(), nil
	}
	s, err := parseReference(rng[:idx])
	if err != nil {
		return "", err
	}
	e, err := parseReference(rng[idx+1:])
	if err != nil {
		return "", err
	}
	if s.kind != e.kind {
		return "", errors.New("range type mismatch")
	}
	so, err := s.offset(dr, dc)
	if err != nil {
		return "", err
	}
	eo, err := e.offset(dr, dc)
	if err != nil {
		return "", err
	}
	so.format(&sb)
	sb.WriteByte(':')
	eo.format(&sb)
	return sb.String(), nil
}

func isTokenByte(c byte) bool {
	return isASCIILetter(c) || isASCIIDigit(c) || c == '\\' || c == '.' || c == '_' || c == '$' || c == ':'
}

func expandSharedFormula(formula string, start, end [2]uint32) (string, error) {
	dr := int64(end[0]) - int64(start[0])
	dc := int64(end[1]) - int64(start[1])
	b := []byte(formula)
	var res []byte
	inQuote := false
	ts, te := 0, 0
	for i, c := range b {
		if !inQuote && isTokenByte(c) {
			te = i + 1
			continue
		}
		if ts < te {
			if c != '(' {
				if t, err := offsetRange(b[ts:te], dr, dc); err == nil {
					res = append(res, t...)
				} else {
					res = append(res, b[ts:te]...)
				}
			} else {
				res = append(res, b[ts:te]...)
			}
		}
		res = append(res, c)
		ts, te = i+1, i+1
		if c == '"' {
			inQuote = !inQuote
		}
	}
	if ts < te {
		if t, err := offsetRange(b[ts:te], dr, dc); err == nil {
			res = append(res, t...)
		} else {
			res = append(res, b[ts:te]...)
		}
	}
	return string(res), nil
}
