// Package calamine reads xls, xlsx, xlsb and ods workbooks. It is a Go port of the
// calamine 0.37.0 Rust crate's readers (src/lib.rs, src/datatype.rs, src/formats.rs).
package calamine

import (
	"math"
	"strconv"
)

// CellErrorType is an error value stored in a cell.
type CellErrorType int

const (
	ErrDiv0 CellErrorType = iota
	ErrNA
	ErrName
	ErrNull
	ErrNum
	ErrRef
	ErrValue
	ErrGettingData
)

func (e CellErrorType) String() string {
	switch e {
	case ErrDiv0:
		return "#DIV/0!"
	case ErrNA:
		return "#N/A"
	case ErrName:
		return "#NAME?"
	case ErrNull:
		return "#NULL!"
	case ErrNum:
		return "#NUM!"
	case ErrRef:
		return "#REF!"
	case ErrValue:
		return "#VALUE!"
	case ErrGettingData:
		return "#DATA!"
	}
	return "#UNKNOWN"
}

// Kind is the type of a cell value.
type Kind int

const (
	Empty Kind = iota
	Int
	Float
	String
	Bool
	DateTime
	DateTimeIso
	DurationIso
	Error
)

// DateTimeType says whether a DateTime value is a point in time or a duration.
type DateTimeType int

const (
	DTDateTime DateTimeType = iota
	DTTimeDelta
)

// Data is one cell value.
type Data struct {
	Kind   Kind
	I      int64
	F      float64
	S      string
	B      bool
	DT     DateTimeType
	Is1904 bool
	E      CellErrorType
}

func (d Data) IsEmpty() bool { return d.Kind == Empty }

// equalDefault mirrors Rust's `v != T::default()` for Data (PartialEq, so NaN != NaN).
func (d Data) isDefault() bool { return d.Kind == Empty }

// Dimensions is an inclusive (row, col) rectangle.
type Dimensions struct {
	StartRow, StartCol uint32
	EndRow, EndCol     uint32
}

func (d Dimensions) Len() uint64 {
	return uint64(d.EndRow-d.StartRow+1) * uint64(d.EndCol-d.StartCol+1)
}

// Cell is a positioned value used to build ranges.
type Cell struct {
	Row, Col uint32
	Val      Data
}

// FCell is a positioned formula string.
type FCell struct {
	Row, Col uint32
	Val      string
}

// Range is a dense rectangle of values, like calamine's Range<Data>.
type Range struct {
	HasStart       bool
	R0, C0, R1, C1 uint32
	Inner          []Data
}

// FRange is a dense rectangle of formula strings (Range<String>).
type FRange struct {
	HasStart       bool
	R0, C0, R1, C1 uint32
	Inner          []string
}

func (r *Range) width() int {
	if !r.HasStart {
		return 0
	}
	return int(r.C1-r.C0) + 1
}

func (r *FRange) width() int {
	if !r.HasStart {
		return 0
	}
	return int(r.C1-r.C0) + 1
}

// RangeFromSparse builds a range from cells in any order; later cells win.
func RangeFromSparse(cells []Cell) Range {
	if len(cells) == 0 {
		return Range{}
	}
	var rs, cs uint32 = math.MaxUint32, math.MaxUint32
	var re, ce uint32
	for _, c := range cells {
		if c.Row < rs {
			rs = c.Row
		}
		if c.Row > re {
			re = c.Row
		}
		if c.Col < cs {
			cs = c.Col
		}
		if c.Col > ce {
			ce = c.Col
		}
	}
	cols := int(ce-cs) + 1
	rows := int(re-rs) + 1
	v := make([]Data, rows*cols)
	for _, c := range cells {
		idx := int(c.Row-rs)*cols + int(c.Col-cs)
		if idx < len(v) {
			v[idx] = c.Val
		}
	}
	return Range{HasStart: true, R0: rs, C0: cs, R1: re, C1: ce, Inner: v}
}

// FRangeFromSparse builds a formula range from cells in any order; later cells win.
func FRangeFromSparse(cells []FCell) FRange {
	if len(cells) == 0 {
		return FRange{}
	}
	var rs, cs uint32 = math.MaxUint32, math.MaxUint32
	var re, ce uint32
	for _, c := range cells {
		if c.Row < rs {
			rs = c.Row
		}
		if c.Row > re {
			re = c.Row
		}
		if c.Col < cs {
			cs = c.Col
		}
		if c.Col > ce {
			ce = c.Col
		}
	}
	cols := int(ce-cs) + 1
	rows := int(re-rs) + 1
	v := make([]string, rows*cols)
	for _, c := range cells {
		idx := int(c.Row-rs)*cols + int(c.Col-cs)
		if idx < len(v) {
			v[idx] = c.Val
		}
	}
	return FRange{HasStart: true, R0: rs, C0: cs, R1: re, C1: ce, Inner: v}
}

// UsedCell is a non-empty cell with its absolute position.
type UsedCell struct {
	Row, Col uint32
	Val      Data
}

// Used returns the non-empty cells in row-major order with absolute positions.
func (r *Range) Used() []UsedCell {
	var out []UsedCell
	w := r.width()
	for i, v := range r.Inner {
		if v.isDefault() {
			continue
		}
		out = append(out, UsedCell{Row: r.R0 + uint32(i/w), Col: r.C0 + uint32(i%w), Val: v})
	}
	return out
}

// Used returns the non-empty formulas in row-major order with absolute positions.
func (r *FRange) Used() []FCell {
	var out []FCell
	w := r.width()
	for i, v := range r.Inner {
		if v == "" {
			continue
		}
		out = append(out, FCell{Row: r.R0 + uint32(i/w), Col: r.C0 + uint32(i%w), Val: v})
	}
	return out
}

// SheetType is the kind of sheet.
type SheetType int

const (
	WorkSheet SheetType = iota
	DialogSheet
	MacroSheet
	ChartSheet
	VbaSheet
)

func (t SheetType) String() string {
	switch t {
	case WorkSheet:
		return "worksheet"
	case DialogSheet:
		return "dialogsheet"
	case MacroSheet:
		return "macrosheet"
	case ChartSheet:
		return "chartsheet"
	case VbaSheet:
		return "vba"
	}
	return "worksheet"
}

// SheetVisible is the visibility of a sheet.
type SheetVisible int

const (
	Visible SheetVisible = iota
	Hidden
	VeryHidden
)

func (v SheetVisible) String() string {
	switch v {
	case Hidden:
		return "hidden"
	case VeryHidden:
		return "veryhidden"
	}
	return "visible"
}

// Sheet is the metadata of one sheet.
type Sheet struct {
	Name    string
	Type    SheetType
	Visible SheetVisible
}

// Name is a defined name and its formula text.
type Name struct {
	Name, Formula string
}

// Workbook is the format-independent reader interface.
type Workbook interface {
	Format() string
	Sheets() []Sheet
	DefinedNames() []Name
	WorksheetRange(name string) (Range, error)
	WorksheetFormula(name string) (FRange, error)
	// MergedCells returns ok=false for formats that do not expose merged regions.
	MergedCells(name string) (dims []Dimensions, ok bool, err error)
	// Properties returns the document properties (ok=false for xls and ods).
	Properties() (props map[string]string, ok bool, err error)
	// VBA returns the VBA project, or nil when the workbook has none.
	VBA() (*VbaProject, error)
	// Pictures returns the embedded pictures read at open time.
	Pictures() []Picture
	// Hyperlinks, Tables and Pivots return ok=false for formats other than xlsx.
	Hyperlinks(name string) ([]Hyperlink, bool, error)
	Tables() ([]Table, bool, error)
	Pivots() ([]Pivot, bool, error)
}

// ---- number formats (src/formats.rs) ----

type cellFormat int

const (
	fmtOther cellFormat = iota
	fmtDateTime
	fmtTimeDelta
)

func isAnyOf(c rune, set string) bool {
	for _, s := range set {
		if c == s {
			return true
		}
	}
	return false
}

func eqIgnoreASCIICase(a, b rune) bool {
	if a < 128 && b < 128 {
		la, lb := a, b
		if la >= 'A' && la <= 'Z' {
			la += 32
		}
		if lb >= 'A' && lb <= 'Z' {
			lb += 32
		}
		return la == lb
	}
	return a == b
}

// detectCustomNumberFormat reports whether a number format code is a date or a duration.
func detectCustomNumberFormat(format string) cellFormat {
	escaped := false
	isQuote := false
	var brackets uint8
	prev := ' '
	hms := false
	ap := false
	for _, s := range format {
		switch {
		case escaped:
			escaped = false
		case s == '_' || s == '\\' || s == '*':
			escaped = true
		case s == '"' && isQuote:
			isQuote = false
		case isQuote:
		case s == '"':
			isQuote = true
		case s == ';':
			return fmtOther
		case s == '[':
			brackets++
		case s == ']' && brackets == 1 && hms:
			return fmtTimeDelta
		case s == ']':
			if brackets > 0 {
				brackets--
			}
		case (s == 'a' || s == 'A') && !ap && brackets == 0:
			ap = true
		case isAnyOf(s, "pm/PM") && ap && brackets == 0:
			return fmtDateTime
		case isAnyOf(s, "dmhysDMHYS") && !ap && brackets == 0:
			return fmtDateTime
		default:
			if hms && eqIgnoreASCIICase(s, prev) {
				// ok
			} else {
				hms = prev == '[' && isAnyOf(s, "mhsMHS")
			}
		}
		prev = s
	}
	return fmtOther
}

func builtinFormatByID(id string) cellFormat {
	switch id {
	case "14", "15", "16", "17", "18", "19", "20", "21", "22", "45", "47":
		return fmtDateTime
	case "27", "28", "29", "30", "31", "32", "33", "34", "35", "36", "50", "51",
		"52", "53", "54", "55", "56", "57", "58":
		return fmtDateTime
	case "46":
		return fmtTimeDelta
	}
	return fmtOther
}

func builtinFormatByCode(code uint16) cellFormat {
	switch {
	case code >= 14 && code <= 22, code >= 27 && code <= 36, code == 45, code == 47, code >= 50 && code <= 58:
		return fmtDateTime
	case code == 46:
		return fmtTimeDelta
	}
	return fmtOther
}

func formatExcelI64(v int64, f *cellFormat, is1904 bool) Data {
	if f != nil {
		switch *f {
		case fmtDateTime:
			return Data{Kind: DateTime, F: float64(v), DT: DTDateTime, Is1904: is1904}
		case fmtTimeDelta:
			return Data{Kind: DateTime, F: float64(v), DT: DTTimeDelta, Is1904: is1904}
		}
	}
	return Data{Kind: Int, I: v}
}

func formatExcelF64(v float64, f *cellFormat, is1904 bool) Data {
	if f != nil {
		switch *f {
		case fmtDateTime:
			return Data{Kind: DateTime, F: v, DT: DTDateTime, Is1904: is1904}
		case fmtTimeDelta:
			return Data{Kind: DateTime, F: v, DT: DTTimeDelta, Is1904: is1904}
		}
	}
	return Data{Kind: Float, F: v}
}

func fmtAt(formats []cellFormat, i int) *cellFormat {
	if i >= 0 && i < len(formats) {
		return &formats[i]
	}
	return nil
}

// ---- date conversion (ExcelDateTime::to_ymd_hms_milli) ----

const (
	daySeconds        = 24.0 * 60.0 * 60.0
	hourSeconds       = 60 * 60
	minuteSeconds     = 60
	yearDays          = 365
	yearDays4         = yearDays*4 + 1
	yearDays100       = yearDays*100 + 25
	yearDays400       = yearDays*400 + 97
	maxSerialDays1900 = 2_958_465
	maxSerialDays1904 = 2_957_003
)

// satU64 mimics Rust's saturating `f64 as u64` cast.
func satU64(f float64) uint64 {
	if math.IsNaN(f) || f <= 0 {
		return 0
	}
	if f >= 18446744073709551615.0 {
		return math.MaxUint64
	}
	return uint64(f)
}

func isLeap(y uint64) bool { return y%4 == 0 && (y%100 != 0 || y%400 == 0) }

// ToYMDHMSMilli converts an Excel serial date to calendar components.
func ToYMDHMSMilli(v float64, is1904 bool) (uint16, uint8, uint8, uint8, uint8, uint8, uint16) {
	months := [12]uint64{31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31}
	days := satU64(math.Floor(v))
	var maxDays uint64 = maxSerialDays1900
	if is1904 {
		maxDays = maxSerialDays1904
	}
	if days > maxDays {
		days = maxDays
	}
	if is1904 {
		days += 111_033
	} else if days > yearDays {
		days += 109_571
	} else {
		days += 109_572
	}
	y400 := days / yearDays400
	days = days % yearDays400
	var y100 uint64
	if days < yearDays100 {
		y100 = days / yearDays100
		days %= yearDays100
	} else {
		y100 = 1 + (days-yearDays100)/(yearDays100-1)
		days = (days - yearDays100) % (yearDays100 - 1)
	}
	var y4 uint64
	nonLeapBlock := false
	if y100 == 0 {
		y4 = days / yearDays4
		days %= yearDays4
	} else if days < yearDays4 {
		y4 = days / (yearDays4 - 1)
		days %= yearDays4 - 1
		nonLeapBlock = true
	} else {
		y4 = 1 + (days-(yearDays4-1))/yearDays4
		days = (days - (yearDays4 - 1)) % yearDays4
	}
	var y1 uint64
	if nonLeapBlock {
		y1 = days / yearDays
		days %= yearDays
	} else if days < yearDays+1 {
		y1 = days / (yearDays + 1)
		days %= yearDays + 1
	} else {
		y1 = 1 + (days-(yearDays+1))/yearDays
		days = (days - (yearDays + 1)) % yearDays
	}
	year := 1600 + y400*400 + y100*100 + y4*4 + y1
	days++
	if isLeap(year) {
		months[1] = 29
	}
	if !is1904 && year == 1900 {
		months[1] = 29
		if math.Trunc(v) == 366.0 {
			days++
		}
	}
	month := uint64(1)
	for _, md := range months {
		if days > md {
			days -= md
			month++
		} else {
			break
		}
	}
	day := days
	_, frac := math.Modf(v) // Rust fract(): NaN for NaN and +-inf
	_, f2 := math.Modf(frac * daySeconds)
	milli := satU64(math.Round(f2 * 1000.0))
	secs := satU64(frac * daySeconds)
	if milli == 1000 {
		secs++
		milli = 0
	}
	hour := secs / hourSeconds
	min := (secs - hour*hourSeconds) / minuteSeconds
	sec := (secs - hour*hourSeconds - min*minuteSeconds) % minuteSeconds
	return uint16(year), uint8(month), uint8(day), uint8(hour), uint8(min), uint8(sec), uint16(milli)
}

// FormatDateTime renders the calendar form used in the JSON dump.
func FormatDateTime(v float64, is1904 bool) string {
	y, mo, d, h, mi, s, ms := ToYMDHMSMilli(v, is1904)
	return pad(int(y), 4) + "-" + pad(int(mo), 2) + "-" + pad(int(d), 2) + "T" +
		pad(int(h), 2) + ":" + pad(int(mi), 2) + ":" + pad(int(s), 2) + "." + pad(int(ms), 3)
}

func pad(v, n int) string {
	s := strconv.Itoa(v)
	for len(s) < n {
		s = "0" + s
	}
	return s
}
