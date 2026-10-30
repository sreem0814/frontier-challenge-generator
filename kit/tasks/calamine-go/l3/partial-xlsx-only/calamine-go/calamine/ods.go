package calamine

// OpenDocument spreadsheet (.ods) reader (port of calamine src/ods.rs).

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"strconv"
	"strings"
)

const odsMaxCells = 100_000_000

var odsMimetype = []byte("application/vnd.oasis.opendocument.spreadsheet")

type odsSheet struct {
	rng Range
	frm FRange
}

// Ods is an opened ods workbook. Everything is parsed at open time.
type Ods struct {
	sheets   map[string]*odsSheet
	meta     []Sheet
	names    []Name
	pictures []Picture
}

func (o *Ods) Format() string       { return "ods" }
func (o *Ods) Sheets() []Sheet      { return o.meta }
func (o *Ods) DefinedNames() []Name { return o.names }
func (o *Ods) WorksheetRange(name string) (Range, error) {
	s, ok := o.sheets[name]
	if !ok {
		return Range{}, fmt.Errorf("worksheet %q not found", name)
	}
	return s.rng, nil
}
func (o *Ods) WorksheetFormula(name string) (FRange, error) {
	s, ok := o.sheets[name]
	if !ok {
		return FRange{}, fmt.Errorf("worksheet %q not found", name)
	}
	return s.frm, nil
}
func (o *Ods) MergedCells(string) ([]Dimensions, bool, error) { return nil, false, nil }

// exact-name zip lookup (ods uses ZipArchive::by_name without the path cache)
func zipReadExact(z *zipPkg, name string) ([]byte, error) {
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

// OpenOds opens an ods package held in memory.
func OpenOds(data []byte) (wb Workbook, err error) {
	defer func() {
		if p := recover(); p != nil {
			wb, err = nil, fmt.Errorf("ods: malformed file (%v)", p)
		}
	}()
	z, err := openZip(data)
	if err != nil {
		return nil, err
	}
	mt, err := zipReadExact(z, "mimetype")
	if err == errZipNotFound {
		return nil, errors.New("mimetype file not found in archive")
	} else if err != nil {
		return nil, err
	}
	if len(mt) < 46 {
		return nil, errors.New("mimetype too short")
	}
	if !bytes.Equal(mt[:46], odsMimetype) {
		return nil, errors.New("invalid mimetype")
	}
	man, err := zipReadExact(z, "META-INF/manifest.xml")
	if err == errZipNotFound {
		return nil, errors.New("META-INF/manifest.xml file not found in archive")
	} else if err != nil {
		return nil, err
	}
	if err := odsCheckPassword(newXMLReader(man)); err != nil {
		return nil, err
	}
	pics, err := zipMediaPictures(z, "Pictures")
	if err != nil {
		return nil, err
	}
	content, err := zipReadExact(z, "content.xml")
	if err == errZipNotFound {
		return nil, errors.New("content.xml file not found in archive")
	} else if err != nil {
		return nil, err
	}
	o := &Ods{sheets: map[string]*odsSheet{}, pictures: pics}
	if err := o.parseContent(newXMLReader(content)); err != nil {
		return nil, err
	}
	return o, nil
}

func odsCheckPassword(xr *xmlReader) error {
	for {
		ev, err := xr.next()
		if err != nil {
			return err
		}
		if ev.kind == evStart && ev.isName("manifest:file-entry") {
			for {
				in, err := xr.next()
				if err != nil {
					return err
				}
				if in.kind == evStart && in.isName("manifest:encryption-data") {
					return errors.New("workbook is password protected")
				}
				if in.kind == evEOF {
					break
				}
			}
		} else if ev.kind == evEOF {
			return nil
		}
	}
}

func parseUsize(s string) (int, error) {
	v, err := strconv.ParseUint(s, 10, 64)
	if err != nil || strings.HasPrefix(s, "-") {
		return 0, errors.New("invalid integer " + s)
	}
	if v > uint64(int(^uint(0)>>1)) {
		return int(^uint(0) >> 1), nil
	}
	return int(v), nil
}

// rustParseUsize mimics str::parse::<usize> (an optional leading '+' is accepted).
func rustParseUsize(s string) (int, error) {
	t := s
	if strings.HasPrefix(t, "+") {
		t = t[1:]
	}
	if t == "" {
		return 0, errors.New("invalid integer")
	}
	for i := 0; i < len(t); i++ {
		if t[i] < '0' || t[i] > '9' {
			return 0, errors.New("invalid integer " + s)
		}
	}
	return parseUsize(t)
}

func (o *Ods) parseContent(xr *xmlReader) error {
	styles := map[string]SheetVisible{}
	var styleName *string
	for {
		ev, err := xr.next()
		if err != nil {
			return err
		}
		switch {
		case ev.kind == evStart && ev.isName("style:style"):
			v, ok, err := rawAttrLookup(ev.attrs, "style:name")
			if err != nil {
				return err
			}
			if ok {
				d, err := decodeAttr(v)
				if err != nil {
					return err
				}
				styleName = &d
			} else {
				styleName = nil
			}
		case ev.kind == evStart && styleName != nil && ev.isName("style:table-properties"):
			vis := Visible
			v, ok, err := rawAttrLookup(ev.attrs, "table:display")
			if err != nil {
				return err
			}
			if ok {
				d, err := decodeAttr(v)
				if err != nil {
					return err
				}
				switch d {
				case "true":
					vis = Visible
				case "false":
					vis = Hidden
				default:
					return errors.New("invalid bool " + d)
				}
			}
			styles[*styleName] = vis
		case ev.kind == evStart && ev.isName("table:table"):
			vis := Visible
			v, ok, err := rawAttrLookup(ev.attrs, "table:style-name")
			if err != nil {
				return err
			}
			if ok {
				d, err := decodeAttr(v)
				if err != nil {
					return err
				}
				if s, ok := styles[d]; ok {
					vis = s
				}
			}
			n, ok, err := rawAttrLookup(ev.attrs, "table:name")
			if err != nil {
				return err
			}
			if ok {
				name, err := decodeAttr(n)
				if err != nil {
					return err
				}
				rng, frm, err := odsReadTable(xr)
				if err != nil {
					return err
				}
				o.meta = append(o.meta, Sheet{Name: name, Type: WorkSheet, Visible: vis})
				o.sheets[name] = &odsSheet{rng: rng, frm: frm}
			}
		case ev.kind == evStart && ev.isName("table:named-expressions"):
			names, err := odsReadNamedExpressions(xr)
			if err != nil {
				return err
			}
			o.names = names
		case ev.kind == evEOF:
			return nil
		}
	}
}

func odsReadTable(xr *xmlReader) (Range, FRange, error) {
	var cells []Data
	var formulas []string
	var rowsRepeats []int
	cols := []int{0}
	totalRows := 0
	for {
		ev, err := xr.next()
		if err != nil {
			return Range{}, FRange{}, err
		}
		switch {
		case ev.kind == evStart && ev.isName("table:table-row"):
			repeats := 1
			v, ok, err := rawAttrLookup(ev.attrs, "table:number-rows-repeated")
			if err != nil {
				return Range{}, FRange{}, err
			}
			if ok {
				d, err := decodeAttr(v)
				if err != nil {
					return Range{}, FRange{}, err
				}
				repeats, err = rustParseUsize(d)
				if err != nil {
					return Range{}, FRange{}, err
				}
			}
			remaining := maxRows - totalRows
			if remaining < 0 {
				remaining = 0
			}
			capped := min(repeats, remaining)
			totalRows += capped
			if err := odsReadRow(xr, &cells, &formulas); err != nil {
				return Range{}, FRange{}, err
			}
			cols = append(cols, len(cells))
			rowsRepeats = append(rowsRepeats, capped)
		case ev.kind == evEnd && ev.isName("table:table"):
			r, err := odsGetRange(cells, cols, rowsRepeats)
			if err != nil {
				return Range{}, FRange{}, err
			}
			f, err := odsGetFRange(formulas, cols, rowsRepeats)
			if err != nil {
				return Range{}, FRange{}, err
			}
			return r, f, nil
		case ev.kind == evEOF:
			return Range{}, FRange{}, eofErr("table:table")
		}
	}
}

func odsReadRow(xr *xmlReader, cells *[]Data, formulas *[]string) error {
	emptyRepeats := 0
	rowStart := len(*cells)
	for {
		ev, err := xr.next()
		if err != nil {
			return err
		}
		switch {
		case ev.kind == evStart && (ev.isName("table:table-cell") || ev.isName("table:covered-table-cell")):
			repeats := 1
			v, ok, err := rawAttrLookup(ev.attrs, "table:number-columns-repeated")
			if err != nil {
				return err
			}
			if ok {
				repeats, err = rustParseUsize(v)
				if err != nil {
					return err
				}
			}
			value, formula, closed, err := odsGetDatatype(xr, ev)
			if err != nil {
				return err
			}
			cur := len(*cells) - rowStart
			remaining := max(maxColumns-cur, 0)
			cappedEmpty := min(emptyRepeats, remaining)
			for i := 0; i < cappedEmpty; i++ {
				*cells = append(*cells, Data{})
				*formulas = append(*formulas, "")
			}
			emptyRepeats = 0
			cur = len(*cells) - rowStart
			remaining = max(maxColumns-cur, 0)
			capped := min(repeats, remaining)
			if value.Kind == Empty && formula == "" {
				emptyRepeats = capped
			} else {
				for i := 0; i < capped; i++ {
					*cells = append(*cells, value)
					*formulas = append(*formulas, formula)
				}
			}
			if !closed {
				if err := xr.readToEnd(ev.name); err != nil {
					return err
				}
			}
		case ev.kind == evEnd && ev.isName("table:table-row"):
			return nil
		default:
			return errors.New("expecting table-cell")
		}
	}
}

func odsGetDatatype(xr *xmlReader, e xmlEvent) (Data, string, bool, error) {
	isString := false
	isValueSet := false
	var val Data
	formula := ""
	var aerr error
	err := iterAttrs(e.attrs, func(k, v string) bool {
		switch {
		case k == "office:value" && !isValueSet:
			f, ok := parseFastFloat(v)
			if !ok {
				aerr = errors.New("invalid float " + v)
				return false
			}
			val = Data{Kind: Float, F: f}
			isValueSet = true
		case (k == "office:string-value" || k == "office:date-value" || k == "office:time-value") && !isValueSet:
			d, err := decodeAttr(v)
			if err != nil {
				aerr = err
				return false
			}
			switch k {
			case "office:date-value":
				val = Data{Kind: DateTimeIso, S: d}
			case "office:time-value":
				val = Data{Kind: DurationIso, S: d}
			default:
				val = Data{Kind: String, S: d}
			}
			isValueSet = true
		case k == "office:boolean-value" && !isValueSet:
			val = Data{Kind: Bool, B: v == "TRUE" || v == "true"}
			isValueSet = true
		case k == "office:value-type" && !isValueSet:
			isString = v == "string"
		case k == "table:formula":
			d, err := decodeAttr(v)
			if err != nil {
				aerr = err
				return false
			}
			formula = d
		}
		return true
	})
	if aerr != nil {
		return Data{}, "", false, aerr
	}
	if err != nil {
		return Data{}, "", false, err
	}
	if isValueSet || !isString {
		return val, formula, false, nil
	}
	var sb strings.Builder
	first := true
	for {
		ev, err := xr.next()
		if err != nil {
			return Data{}, "", false, err
		}
		switch {
		case ev.kind == evText:
			t, err := xml10Content(ev.text)
			if err != nil {
				return Data{}, "", false, err
			}
			sb.WriteString(t)
		case ev.kind == evRef:
			if err := unescapeRef(ev.text, &sb); err != nil {
				return Data{}, "", false, err
			}
		case ev.kind == evEnd && (ev.isName("table:table-cell") || ev.isName("table:covered-table-cell")):
			return Data{Kind: String, S: sb.String()}, formula, true, nil
		case ev.kind == evStart && ev.isName("office:annotation"):
			for {
				in, err := xr.next()
				if err != nil {
					return Data{}, "", false, err
				}
				if in.kind == evEnd && in.isName("office:annotation") {
					break
				}
				if in.kind == evEOF {
					return Data{}, "", false, eofErr("office:annotation")
				}
			}
		case ev.kind == evStart && ev.isName("text:p"):
			if first {
				first = false
			} else {
				sb.WriteByte('\n')
			}
		case ev.kind == evStart && ev.isName("text:s"):
			count := 1
			v, ok, err := rawAttrLookup(ev.attrs, "text:c")
			if err != nil {
				return Data{}, "", false, err
			}
			if ok {
				d, err := decodeAttr(v)
				if err != nil {
					return Data{}, "", false, err
				}
				count, err = rustParseUsize(d)
				if err != nil {
					return Data{}, "", false, err
				}
			}
			for i := 0; i < count; i++ {
				sb.WriteByte(' ')
			}
		case ev.kind == evEOF:
			return Data{}, "", false, eofErr("table:table-cell")
		}
	}
}

func odsReadNamedExpressions(xr *xmlReader) ([]Name, error) {
	var names []Name
	for {
		ev, err := xr.next()
		if err != nil {
			return nil, err
		}
		switch {
		case ev.kind == evStart && (ev.isName("table:named-range") || ev.isName("table:named-expression")):
			name, formula := "", ""
			var aerr error
			err := iterAttrs(ev.attrs, func(k, v string) bool {
				switch k {
				case "table:name":
					name, aerr = decodeAttr(v)
				case "table:cell-range-address", "table:expression":
					formula, aerr = decodeAttr(v)
				}
				return aerr == nil
			})
			if aerr != nil {
				return nil, aerr
			}
			if err != nil {
				return nil, err
			}
			names = append(names, Name{name, formula})
		case ev.kind == evEnd && (ev.isName("table:named-range") || ev.isName("table:named-expression")):
		case ev.kind == evEnd && ev.isName("table:named-expressions"):
			return names, nil
		default:
			return nil, errors.New("expecting table:named-expressions")
		}
	}
}

// odsGetRange is calamine's get_range for values.
func odsGetRange(cells []Data, cols []int, rowsRepeats []int) (Range, error) {
	isDef := func(d Data) bool { return d.Kind == Empty }
	rowMin, rowMax, colMin, colMax, firstEmpty, ok := odsBounds(len(cols), func(i int) (int, int, bool) {
		row := cells[cols[i]:cols[i+1]]
		p, q := -1, -1
		for j, c := range row {
			if !isDef(c) {
				if p < 0 {
					p = j
				}
				q = j
			}
		}
		return p, q, p >= 0
	}, rowsRepeats)
	if !ok {
		return Range{}, nil
	}
	rowWidth := colMax + 1 - colMin
	var out []Data
	empty := make([]Data, colMax+1)
	emptyRepeats, consecutive := 0, 0
	nrows := len(cols) - 1
	take := rowMax + 1 // evaluated once, like the Rust iterator's take(row_max + 1)
	for k := 0; k < take && rowMin+k < nrows; k++ {
		i := rowMin + k
		row := cells[cols[i]:cols[i+1]]
		reps := rowsRepeats[i]
		allEmpty := true
		for _, c := range row {
			if !isDef(c) {
				allEmpty = false
				break
			}
		}
		if allEmpty {
			emptyRepeats += reps
			consecutive++
			continue
		}
		if emptyRepeats > 0 {
			if len(out)+emptyRepeats*rowWidth > odsMaxCells {
				return Range{}, errors.New("cell limit exceeded")
			}
			rowMax = rowMax + emptyRepeats - consecutive
			for r := 0; r < emptyRepeats; r++ {
				out = append(out, empty[colMin:]...)
			}
			emptyRepeats, consecutive = 0, 0
		}
		if reps > 1 {
			rowMax = rowMax + reps - 1
		}
		if len(out)+reps*rowWidth > odsMaxCells {
			return Range{}, errors.New("cell limit exceeded")
		}
		for r := 0; r < reps; r++ {
			switch {
			case len(row) < colMax+1:
				out = append(out, row[colMin:]...)
				out = append(out, empty[len(row):]...)
			case len(row) == colMax+1:
				out = append(out, row[colMin:]...)
			default:
				out = append(out, row[colMin:colMax+1]...)
			}
		}
	}
	rowMin += firstEmpty
	rowMax += firstEmpty
	return Range{HasStart: true, R0: uint32(rowMin), C0: uint32(colMin), R1: uint32(rowMax), C1: uint32(colMax), Inner: out}, nil
}

// odsGetFRange is calamine's get_range for formula strings.
func odsGetFRange(cells []string, cols []int, rowsRepeats []int) (FRange, error) {
	rowMin, rowMax, colMin, colMax, firstEmpty, ok := odsBounds(len(cols), func(i int) (int, int, bool) {
		row := cells[cols[i]:cols[i+1]]
		p, q := -1, -1
		for j, c := range row {
			if c != "" {
				if p < 0 {
					p = j
				}
				q = j
			}
		}
		return p, q, p >= 0
	}, rowsRepeats)
	if !ok {
		return FRange{}, nil
	}
	rowWidth := colMax + 1 - colMin
	var out []string
	empty := make([]string, colMax+1)
	emptyRepeats, consecutive := 0, 0
	nrows := len(cols) - 1
	take := rowMax + 1 // evaluated once, like the Rust iterator's take(row_max + 1)
	for k := 0; k < take && rowMin+k < nrows; k++ {
		i := rowMin + k
		row := cells[cols[i]:cols[i+1]]
		reps := rowsRepeats[i]
		allEmpty := true
		for _, c := range row {
			if c != "" {
				allEmpty = false
				break
			}
		}
		if allEmpty {
			emptyRepeats += reps
			consecutive++
			continue
		}
		if emptyRepeats > 0 {
			if len(out)+emptyRepeats*rowWidth > odsMaxCells {
				return FRange{}, errors.New("cell limit exceeded")
			}
			rowMax = rowMax + emptyRepeats - consecutive
			for r := 0; r < emptyRepeats; r++ {
				out = append(out, empty[colMin:]...)
			}
			emptyRepeats, consecutive = 0, 0
		}
		if reps > 1 {
			rowMax = rowMax + reps - 1
		}
		if len(out)+reps*rowWidth > odsMaxCells {
			return FRange{}, errors.New("cell limit exceeded")
		}
		for r := 0; r < reps; r++ {
			switch {
			case len(row) < colMax+1:
				out = append(out, row[colMin:]...)
				out = append(out, empty[len(row):]...)
			case len(row) == colMax+1:
				out = append(out, row[colMin:]...)
			default:
				out = append(out, row[colMin:colMax+1]...)
			}
		}
	}
	rowMin += firstEmpty
	rowMax += firstEmpty
	return FRange{HasStart: true, R0: uint32(rowMin), C0: uint32(colMin), R1: uint32(rowMax), C1: uint32(colMax), Inner: out}, nil
}

// odsBounds finds the first/last non-empty rows and the column span.
func odsBounds(ncols int, rowSpan func(i int) (int, int, bool), rowsRepeats []int) (rowMin, rowMax, colMin, colMax, firstEmpty int, ok bool) {
	rowMin = -1
	colMin = int(^uint(0) >> 1)
	for i := 0; i+1 < ncols; i++ {
		p, q, nonEmpty := rowSpan(i)
		if !nonEmpty {
			continue
		}
		if rowMin < 0 {
			rowMin = i
			sum := 0
			for _, r := range rowsRepeats[:i] {
				sum += r
			}
			firstEmpty = sum - i
			if firstEmpty < 0 {
				firstEmpty = 0
			}
		}
		rowMax = i
		if p < colMin {
			colMin = p
		}
		if q > colMax {
			colMax = q
		}
	}
	if rowMin < 0 {
		return 0, 0, 0, 0, 0, false
	}
	return rowMin, rowMax, colMin, colMax, firstEmpty, true
}
