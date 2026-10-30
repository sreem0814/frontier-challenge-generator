package calamine

// Workbook properties (xlsx, xlsb), hyperlinks, tables and pivot tables (xlsx).

import (
	"bytes"
	"errors"
	"fmt"
	"strings"
)

// PropertyNames lists the document properties in output order.
var PropertyNames = []string{"creator", "last_modified_by", "created", "modified", "title", "subject",
	"description", "keywords", "category", "content_status", "revision", "version", "application",
	"app_version", "company", "template", "manager"}

var corePropTags = map[string]string{
	"creator": "creator", "lastModifiedBy": "last_modified_by", "created": "created", "modified": "modified",
	"title": "title", "subject": "subject", "description": "description", "keywords": "keywords",
	"category": "category", "contentStatus": "content_status", "revision": "revision", "version": "version",
	"Application": "application", "AppVersion": "app_version", "Company": "company", "Template": "template",
	"Manager": "manager",
}

var appPropTags = map[string]string{
	"Application": "application", "AppVersion": "app_version", "Company": "company", "Template": "template",
	"Manager": "manager",
}

func readPropsPart(z *zipPkg, path string, tags map[string]string, props map[string]string) error {
	xr, err := z.xml(path)
	if err == errZipNotFound {
		return nil
	} else if err != nil {
		return err
	}
	current := ""
	var value strings.Builder
	for {
		ev, err := xr.next()
		if err != nil {
			return err
		}
		switch ev.kind {
		case evEOF:
			return nil
		case evStart:
			value.Reset()
			current = tags[string(ev.localName())]
		case evText:
			if current != "" {
				t, err := xml10Content(ev.text)
				if err != nil {
					return err
				}
				value.WriteString(t)
			}
		case evRef:
			if current != "" {
				if err := unescapeRef(ev.text, &value); err != nil {
					return err
				}
			}
		case evEnd:
			if current != "" && value.Len() > 0 {
				props[current] = value.String()
				value.Reset()
			}
			current = ""
		}
	}
}

func workbookProperties(z *zipPkg) (map[string]string, error) {
	props := map[string]string{}
	if err := readPropsPart(z, "docProps/core.xml", corePropTags, props); err != nil {
		return nil, err
	}
	if err := readPropsPart(z, "docProps/app.xml", appPropTags, props); err != nil {
		return nil, err
	}
	return props, nil
}

// ---- hyperlinks ----

// Hyperlink is one <hyperlink> of an xlsx sheet; nil pointers are absent attributes.
type Hyperlink struct {
	Range                              Dimensions
	Target, Location, Display, Tooltip *string
}

func (x *Xlsx) sheetPath(name string) (string, bool) {
	for _, s := range x.sheets {
		if s.name == name {
			return s.path, true
		}
	}
	return "", false
}

func (x *Xlsx) hyperlinkRels(sheetPath string) (map[string]string, error) {
	rels := map[string]string{}
	i := strings.LastIndexByte(sheetPath, '/')
	if i < 0 {
		return rels, nil
	}
	xr, err := x.z.xml(sheetPath[:i] + "/_rels" + sheetPath[i:] + ".rels")
	if err == errZipNotFound {
		return rels, nil
	} else if err != nil {
		return nil, err
	}
	for {
		ev, err := xr.next()
		if err != nil {
			return nil, err
		}
		switch {
		case ev.kind == evStart && ev.isLocal("Relationship"):
			v, has, err := getAttrs(ev.attrs, "Id", "Target", "Type")
			if err != nil {
				return nil, err
			}
			if has[2] && strings.HasSuffix(v[2], "/relationships/hyperlink") && has[0] && v[0] != "" {
				t := ""
				if has[1] {
					d, err := decodeAttr(v[1])
					if err != nil {
						return nil, err
					}
					t = unescapeXMLEscapes(d)
				}
				rels[v[0]] = t
			}
		case ev.kind == evEnd && ev.isLocal("Relationships"), ev.kind == evEOF:
			return rels, nil
		}
	}
}

// Hyperlinks returns the hyperlinks of a sheet (xlsx only).
func (x *Xlsx) Hyperlinks(name string) ([]Hyperlink, bool, error) {
	path, ok := x.sheetPath(name)
	if !ok {
		return nil, true, fmt.Errorf("worksheet %q not found", name)
	}
	rels, err := x.hyperlinkRels(path)
	if err != nil {
		return nil, true, err
	}
	xr, err := x.z.xml(path)
	if err == errZipNotFound {
		return nil, true, fmt.Errorf("worksheet %q not found", name)
	} else if err != nil {
		return nil, true, err
	}
	var links []Hyperlink
	for {
		ev, err := xr.next()
		if err != nil {
			return nil, true, err
		}
		if ev.kind == evEOF {
			return links, true, nil
		}
		if ev.kind != evStart || !ev.isLocal("hyperlinks") {
			continue
		}
		for {
			in, err := xr.next()
			if err != nil {
				return nil, true, err
			}
			if in.kind == evEOF {
				return nil, true, eofErr("hyperlinks")
			}
			if in.kind == evEnd && in.isLocal("hyperlinks") {
				return links, true, nil
			}
			if in.kind != evStart || !in.isLocal("hyperlink") {
				continue
			}
			var h Hyperlink
			hasRange := false
			var rid *string
			var aerr error
			ierr := iterAttrs(in.attrs, func(k, v string) bool {
				switch {
				case k == "ref":
					h.Range, aerr = getDimension(v)
					hasRange = true
				case k == "location", k == "display", k == "tooltip":
					d, err := decodeAttr(v)
					if err != nil {
						aerr = err
						break
					}
					d = unescapeXMLEscapes(d)
					switch k {
					case "location":
						h.Location = &d
					case "display":
						h.Display = &d
					default:
						h.Tooltip = &d
					}
				case localNameMatches(k, "id"):
					vv := v
					rid = &vv
				}
				return aerr == nil
			})
			if aerr != nil {
				return nil, true, aerr
			}
			if ierr != nil {
				return nil, true, ierr
			}
			if !hasRange {
				continue
			}
			if rid != nil {
				if t, ok := rels[*rid]; ok {
					tt := t
					h.Target = &tt
				}
			}
			links = append(links, h)
		}
	}
}

// ---- tables ----

// Table is an xlsx table and its data range (without the header row).
type Table struct {
	Name, Sheet string
	Columns     []string
	Data        Range
	Err         error // table_by_name failed for this table
}

const tableRelType = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/table"

type tableMeta struct {
	name, sheet string
	columns     []string
	dims        Dimensions
}

func rustParseU32Strict(s string) (uint32, error) {
	v, ok := rustParseU32(s)
	if !ok {
		return 0, errors.New("invalid integer " + s)
	}
	return v, nil
}

func (x *Xlsx) readTableMeta() ([]tableMeta, error) {
	var out []tableMeta
	for _, sh := range x.sheets {
		i := strings.LastIndexByte(sh.path, '/')
		if i < 0 {
			panic("should be in a folder")
		}
		base, file := sh.path[:i], sh.path[i:]
		xr, err := x.z.xml(base + "/_rels" + file + ".rels")
		if err == errZipNotFound {
			continue
		} else if err != nil {
			return nil, err
		}
		var locations []string
	rels:
		for {
			ev, err := xr.next()
			if err != nil {
				return nil, err
			}
			switch {
			case ev.kind == evStart && ev.isLocal("Relationship"):
				v, has, err := getAttrs(ev.attrs, "Id", "Target", "Type")
				if err != nil {
					return nil, err
				}
				if has[2] && v[2] == tableRelType {
					t := ""
					if has[1] {
						if t, err = decodeAttr(v[1]); err != nil {
							return nil, err
						}
					}
					switch {
					case strings.HasPrefix(t, "../"):
						j := strings.LastIndexByte(base, '/')
						if j < 0 {
							panic("must be a parent folder")
						}
						locations = append(locations, base[:j]+t[2:])
					case strings.HasPrefix(t, "/"):
						locations = append(locations, t[1:])
					case t != "":
						locations = append(locations, t)
					}
				}
			case ev.kind == evEnd && ev.isLocal("Relationships"):
				break rels
			case ev.kind == evEOF:
				return nil, eofErr("Relationships")
			}
		}
		for _, loc := range locations {
			tx, err := x.z.xml(loc)
			if err == errZipNotFound {
				continue
			} else if err != nil {
				return nil, err
			}
			name, ref := "", ""
			var header, totals uint32 = 1, 0
			var cols []string
		tbl:
			for {
				ev, err := tx.next()
				if err != nil {
					return nil, err
				}
				switch {
				case ev.kind == evStart && ev.isLocal("table"):
					var aerr error
					ierr := iterAttrs(ev.attrs, func(k, v string) bool {
						switch k {
						case "displayName":
							name, aerr = decodeAttr(v)
						case "ref":
							ref = v
						case "headerRowCount":
							header, aerr = rustParseU32Strict(v)
						case "totalsRowCount":
							totals, aerr = rustParseU32Strict(v)
						}
						return aerr == nil
					})
					if aerr != nil {
						return nil, aerr
					}
					if ierr != nil {
						return nil, ierr
					}
				case ev.kind == evStart && ev.isLocal("tableColumn"):
					v, ok, err := rawAttrLookup(ev.attrs, "name")
					if err != nil {
						return nil, err
					}
					if ok {
						d, err := decodeAttr(v)
						if err != nil {
							return nil, err
						}
						cols = append(cols, d)
					}
				case ev.kind == evEnd && ev.isLocal("table"):
					break tbl
				case ev.kind == evEOF:
					return nil, eofErr("Table")
				}
			}
			d, err := getDimension(ref)
			if err != nil {
				return nil, err
			}
			if header != 0 {
				d.StartRow += header
			}
			if totals != 0 {
				d.EndRow -= header // calamine subtracts the header count here
			}
			out = append(out, tableMeta{name, sh.name, cols, d})
		}
	}
	return out, nil
}

// subRange is calamine's Range::range(start, end).
func subRange(r Range, d Dimensions) Range {
	if d.StartRow > d.EndRow || (d.StartRow == d.EndRow && d.StartCol > d.EndCol) {
		panic("invalid range bounds")
	}
	h := uint32(d.EndRow - d.StartRow + 1)
	w := uint32(d.EndCol - d.StartCol + 1)
	other := Range{HasStart: true, R0: d.StartRow, C0: d.StartCol, R1: d.EndRow, C1: d.EndCol,
		Inner: make([]Data, int(h*w))}
	var sr0, sc0, sr1, sc1 uint32
	if r.HasStart {
		sr0, sc0, sr1, sc1 = r.R0, r.C0, r.R1, r.C1
	}
	startRow, endRow := max(sr0, d.StartRow), min(sr1, d.EndRow)
	startCol, endCol := max(sc0, d.StartCol), min(sc1, d.EndCol)
	if startRow > endRow || startCol > endCol {
		return other
	}
	if len(r.Inner) == 0 {
		panic("chunk size must be non-zero") // an empty range has width 0 in calamine
	}
	sw := int(sc1-sc0) + 1
	ow := int(w)
	for row := startRow; row <= endRow; row++ {
		si := int(row-sr0) * sw
		oi := int(row-d.StartRow) * ow
		if si >= len(r.Inner) || oi >= len(other.Inner) {
			break
		}
		copy(other.Inner[oi+int(startCol-d.StartCol):oi+int(endCol-d.StartCol)+1],
			r.Inner[si+int(startCol-sc0):si+int(endCol-sc0)+1])
	}
	return other
}

// Tables loads every table of the workbook in sheet order and resolves its data range.
func (x *Xlsx) Tables() ([]Table, bool, error) {
	metas, err := x.readTableMeta()
	if err != nil {
		return nil, true, err
	}
	var out []Table
	for _, m := range metas {
		// table_by_name looks the name up again: the first table with this name wins
		var first tableMeta
		for _, t := range metas {
			if t.name == m.name {
				first = t
				break
			}
		}
		out = append(out, x.tableByMeta(first))
	}
	return out, true, nil
}

func (x *Xlsx) tableByMeta(m tableMeta) (t Table) {
	t = Table{Name: m.name, Sheet: m.sheet, Columns: m.columns}
	defer func() {
		if e := recover(); e != nil {
			t.Err = fmt.Errorf("panic: %v", e)
		}
	}()
	r, err := x.WorksheetRange(m.sheet)
	if err != nil {
		t.Err = err
		return t
	}
	t.Data = subRange(r, m.dims)
	return t
}

// ---- pivot tables ----

// Pivot is a pivot table and the rows of its cache (the first row holds the field names).
type Pivot struct {
	Sheet, Name string
	Rows        [][]Data
	Err         error // reading the cache failed for this pivot table
}

const (
	pivotTableRel  = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/pivotTable"
	pivotCacheDef  = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/pivotCacheDefinition"
	pivotCacheRecs = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/pivotCacheRecords"
)

// relTargetsOfType reads a .rels part; missing part handling is left to the caller.
func (x *Xlsx) relTargetsOfType(relPath, typ string, decodeAll bool) ([]string, bool, error) {
	xr, err := x.z.xml(relPath)
	if err == errZipNotFound {
		return nil, false, nil
	} else if err != nil {
		return nil, true, err
	}
	var out []string
	for {
		ev, err := xr.next()
		if err != nil {
			return nil, true, err
		}
		switch {
		case ev.kind == evStart && ev.isLocal("Relationship"):
			v, has, err := getAttrs(ev.attrs, "Target", "Type")
			if err != nil {
				return nil, true, err
			}
			if has[1] && v[1] == typ {
				t := ""
				if has[0] {
					if t, err = decodeAttr(v[0]); err != nil {
						return nil, true, err
					}
				}
				out = append(out, t)
			} else if has[0] && decodeAll {
				if _, err := decodeAttr(v[0]); err != nil {
					return nil, true, err
				}
			}
		case ev.kind == evEnd && ev.isLocal("Relationships"):
			return out, true, nil
		case ev.kind == evEOF:
			return nil, true, eofErr("Relationships")
		}
	}
}

func splitParent(p string) (string, string) {
	i := strings.LastIndexByte(p, '/')
	if i < 0 {
		panic("should be in a folder")
	}
	return p[:i], p[i+1:]
}

type pivotRef struct{ name, sheet, records, defs string }

func (x *Xlsx) pivotRefs() ([]pivotRef, error) {
	var out []pivotRef
	for _, sh := range x.sheets {
		i := strings.LastIndexByte(sh.path, '/')
		if i < 0 {
			panic("should be in a folder")
		}
		base, file := sh.path[:i], sh.path[i:]
		targets, ok, err := x.relTargetsOfType(base+"/_rels"+file+".rels", pivotTableRel, false)
		if err != nil {
			return nil, err
		}
		if !ok {
			continue
		}
		var paths []string
		for _, t := range targets {
			if rest, ok := strings.CutPrefix(t, "../"); ok {
				parent, _ := splitParent(base)
				paths = append(paths, parent+"/"+rest)
			} else if t != "" {
				paths = append(paths, t)
			}
		}
		for _, pp := range paths {
			name, err := x.pivotName(pp)
			if err != nil {
				return nil, err
			}
			defs, err := x.pivotLinked(pp, pivotCacheDef, "pivot cache definition", "")
			if err != nil {
				return nil, err
			}
			recs, err := x.pivotLinked(defs, pivotCacheRecs, "pivot cache record", x.xlPath+"pivotCache")
			if err != nil {
				return nil, err
			}
			out = append(out, pivotRef{name, sh.name, recs, defs})
		}
	}
	return out, nil
}

// pivotLinked follows the single relationship of the given type from path's .rels part.
func (x *Xlsx) pivotLinked(path, typ, what, cachePath string) (string, error) {
	base, file := splitParent(path)
	relPath := base + "/_rels/" + file + ".rels"
	targets, ok, err := x.relTargetsOfType(relPath, typ, true)
	if err != nil {
		return "", err
	}
	if !ok {
		return "", errors.New("file not found: " + relPath)
	}
	found := ""
	have := false
	for _, t := range targets {
		if have {
			return "", fmt.Errorf("multiple %s relationships found for one pivot table", what)
		}
		if cachePath == "" {
			if rest, ok := strings.CutPrefix(t, "../"); ok {
				parent, _ := splitParent(base)
				found, have = parent+"/"+rest, true
			} else if t != "" {
				found, have = t, true
			}
		} else {
			if strings.HasPrefix(t, cachePath) {
				found, have = t, true
			} else if t != "" {
				found, have = cachePath+"/"+t, true
			}
		}
	}
	if !have {
		return "", fmt.Errorf("no %s found for pivot table", what)
	}
	return found, nil
}

func (x *Xlsx) pivotName(path string) (string, error) {
	xr, err := x.z.xml(path)
	if err == errZipNotFound {
		return "", errors.New("file not found: " + path)
	} else if err != nil {
		return "", err
	}
	var name *string
	for {
		ev, err := xr.next()
		if err != nil {
			return "", err
		}
		switch {
		case ev.kind == evStart && ev.isLocal("pivotTableDefinition"):
			v, ok, err := rawAttrLookup(ev.attrs, "name")
			if err != nil {
				return "", err
			}
			if ok {
				if name != nil {
					return "", errors.New("multiple name entries for one pivot table path")
				}
				d, err := decodeAttr(v)
				if err != nil {
					return "", err
				}
				name = &d
			}
		case ev.kind == evEnd && ev.isLocal("pivotTableDefinition"):
			if name == nil {
				return "", errors.New("no name for pivot table")
			}
			return *name, nil
		case ev.kind == evEOF:
			return "", eofErr("pivotTableDefinition")
		}
	}
}

type pivotItem struct {
	tag    byte // s n m e b d
	val    string
	hasVal bool
}

func itemTag(local string) (byte, bool) {
	switch local {
	case "s", "n", "m", "e", "b", "d":
		return local[0], true
	}
	return 0, false
}

func parseItem(it pivotItem) Data {
	if !it.hasVal {
		return Data{}
	}
	v := it.val
	switch it.tag {
	case 'm':
		return Data{}
	case 's':
		return Data{Kind: String, S: v}
	case 'n':
		if strings.Contains(v, ".") {
			if f, ok := parseFastFloat(v); ok {
				return Data{Kind: Float, F: f}
			}
			return Data{Kind: Error, E: ErrGettingData}
		}
		if n, ok := atoiI64(v); ok {
			return Data{Kind: Int, I: n}
		}
		return Data{Kind: Error, E: ErrGettingData}
	case 'd':
		return Data{Kind: DateTimeIso, S: v}
	case 'b':
		switch v {
		case "0", "false":
			return Data{Kind: Bool, B: false}
		case "1", "true":
			return Data{Kind: Bool, B: true}
		}
		return Data{Kind: Error, E: ErrGettingData}
	}
	return Data{Kind: Error, E: ErrRef}
}

// atoiI64 is atoi_simd::parse::<i64, SKIP_ZEROES=true, SKIP_PLUS=false>.
func atoiI64(s string) (int64, bool) {
	neg := false
	t := s
	if strings.HasPrefix(t, "-") {
		neg = true
		t = t[1:]
	}
	if t == "" {
		return 0, false
	}
	var v uint64
	for i := 0; i < len(t); i++ {
		c := t[i]
		if c < '0' || c > '9' {
			return 0, false
		}
		d := uint64(c - '0')
		if v > (1<<63)/10 {
			return 0, false
		}
		v = v*10 + d
	}
	if neg {
		if v > 1<<63 {
			return 0, false
		}
		return -int64(v), true
	}
	if v > 1<<63-1 {
		return 0, false
	}
	return int64(v), true
}

func (x *Xlsx) pivotData(p pivotRef) ([][]Data, error) {
	xr, err := x.z.xml(p.defs)
	if err == errZipNotFound {
		return nil, errors.New("file not found: " + p.defs)
	} else if err != nil {
		return nil, err
	}
	var fields [][]pivotItem
	var names []string
	for {
		ev, err := xr.next()
		if err != nil {
			panic(err.Error())
		}
		if ev.kind == evEOF {
			break
		}
		if ev.kind != evStart {
			continue
		}
		switch string(ev.localName()) {
		case "cacheField":
			v, has, err := getAttrs(ev.attrs, "name", "formula")
			if err != nil {
				return nil, err
			}
			if has[0] {
				d, err := decodeAttr(v[0])
				if err != nil {
					return nil, err
				}
				names = append(names, d)
				fields = append(fields, nil)
			}
			if has[1] && len(names) > 0 {
				names = names[:len(names)-1]
				fields = fields[:len(fields)-1]
			}
		case "groupItems":
			if len(names) > 0 {
				names = names[:len(names)-1]
				fields = fields[:len(fields)-1]
			}
		default:
			if tag, ok := itemTag(string(ev.localName())); ok {
				v, has, err := rawAttrLookup(ev.attrs, "v")
				if err != nil {
					return nil, err
				}
				if len(fields) > 0 {
					fields[len(fields)-1] = append(fields[len(fields)-1], pivotItem{tag, v, has})
				}
			}
		}
	}
	defs := map[string][]pivotItem{}
	for i := 0; i < len(fields) && i < len(names); i++ {
		defs[names[i]] = fields[i]
	}
	rr, err := x.z.xml(p.records)
	if err == errZipNotFound {
		return nil, errors.New("file not found: " + p.records)
	} else if err != nil {
		return nil, err
	}
	var rows [][]Data
	for {
		// one iterator step
		var row []Data
		col := 0
		done := false
		for {
			ev, err := rr.next()
			if err != nil {
				return nil, err
			}
			if ev.kind == evEOF {
				done = true
				break
			}
			if ev.kind == evStart && ev.isLocal("x") {
				v, ok, err := rawAttrLookup(ev.attrs, "v")
				if err != nil {
					return nil, err
				}
				if ok {
					pos, ok := atoiUsize(v)
					if !ok {
						return nil, errors.New("pivot cache x:v attribute must be a number")
					}
					items, found := defs[names[col]]
					if !found {
						panic("no definition for field")
					}
					row = append(row, parseItem(items[pos]))
				}
				col++
				continue
			}
			if ev.kind == evEnd && ev.isLocal("r") {
				break
			}
			if ev.kind == evStart && ev.isLocal("pivotCacheRecords") {
				row = nil
				for _, n := range names {
					row = append(row, Data{Kind: String, S: n})
				}
				break
			}
			if ev.kind == evStart {
				if tag, ok := itemTag(string(ev.localName())); ok {
					v, has, err := rawAttrLookup(ev.attrs, "v")
					if err != nil {
						return nil, err
					}
					row = append(row, parseItem(pivotItem{tag, v, has}))
					col++
				}
			}
		}
		if done {
			return rows, nil
		}
		rows = append(rows, row)
	}
}

// Pivots returns every pivot table with its cache rows (xlsx only).
func (x *Xlsx) Pivots() ([]Pivot, bool, error) {
	refs, err := x.pivotRefs()
	if err != nil {
		return nil, true, err
	}
	var out []Pivot
	for _, r := range refs {
		// pivot_table_data looks the pivot up by (name, sheet): the first match wins
		first := r
		for _, q := range refs {
			if q.name == r.name && q.sheet == r.sheet {
				first = q
				break
			}
		}
		rows, err := x.pivotDataSafe(first)
		p := Pivot{Sheet: r.Sheet(), Name: r.name, Rows: rows}
		if err != nil {
			p.Rows = nil
			p.Err = err
		}
		out = append(out, p)
	}
	return out, true, nil
}

func (r pivotRef) Sheet() string { return r.sheet }

func (x *Xlsx) pivotDataSafe(p pivotRef) (rows [][]Data, err error) {
	defer func() {
		if e := recover(); e != nil {
			rows, err = nil, fmt.Errorf("panic: %v", e)
		}
	}()
	return x.pivotData(p)
}

var _ = bytes.Equal
