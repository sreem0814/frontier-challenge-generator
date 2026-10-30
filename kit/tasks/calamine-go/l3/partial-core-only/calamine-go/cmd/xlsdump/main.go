// Command xlsdump prints a workbook as JSON in the format of the task description ("Output format").
package main

import (
	"bufio"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"math"
	"os"
	"strconv"

	"calaminego/calamine"
)

func jstr(w *bufio.Writer, s string) {
	b, _ := json.Marshal(s)
	w.Write(b)
}

func jnum(w *bufio.Writer, f float64) {
	switch {
	case math.IsNaN(f):
		w.WriteString(`"NaN"`)
	case math.IsInf(f, 1):
		w.WriteString(`"inf"`)
	case math.IsInf(f, -1):
		w.WriteString(`"-inf"`)
	default:
		w.WriteString(strconv.FormatFloat(f, 'g', -1, 64))
	}
}

func writeValue(w *bufio.Writer, d calamine.Data) {
	switch d.Kind {
	case calamine.Int:
		w.WriteString(`"i",`)
		w.WriteString(strconv.FormatInt(d.I, 10))
	case calamine.Float:
		w.WriteString(`"f",`)
		jnum(w, d.F)
	case calamine.String:
		w.WriteString(`"s",`)
		jstr(w, d.S)
	case calamine.Bool:
		if d.B {
			w.WriteString(`"b",true`)
		} else {
			w.WriteString(`"b",false`)
		}
	case calamine.DateTime:
		w.WriteString(`"d",`)
		jnum(w, d.F)
		if d.DT == calamine.DTTimeDelta {
			w.WriteString(`,"timedelta",`)
		} else {
			w.WriteString(`,"datetime",`)
		}
		jstr(w, calamine.FormatDateTime(d.F, d.Is1904))
	case calamine.DateTimeIso:
		w.WriteString(`"di",`)
		jstr(w, d.S)
	case calamine.DurationIso:
		w.WriteString(`"du",`)
		jstr(w, d.S)
	case calamine.Error:
		w.WriteString(`"e",`)
		jstr(w, d.E.String())
	}
}

func u(w *bufio.Writer, v uint32) { w.WriteString(strconv.FormatUint(uint64(v), 10)) }

func dump(w *bufio.Writer, path string) {
	wb, err := calamine.Open(path)
	if err != nil {
		w.WriteString(`{"error":"open","detail":`)
		jstr(w, err.Error())
		w.WriteString("}\n")
		return
	}
	w.WriteString(`{"format":`)
	jstr(w, wb.Format())
	w.WriteString(`,"sheets":[`)
	for i, sh := range wb.Sheets() {
		if i > 0 {
			w.WriteByte(',')
		}
		w.WriteString(`{"name":`)
		jstr(w, sh.Name)
		w.WriteString(`,"type":`)
		jstr(w, sh.Type.String())
		w.WriteString(`,"visible":`)
		jstr(w, sh.Visible.String())
		rng, err := safeRange(wb, sh.Name)
		if err != nil {
			w.WriteString(`,"dims":null,"cells":"error"`)
		} else {
			if rng.HasStart {
				w.WriteString(`,"dims":[`)
				u(w, rng.R0)
				w.WriteByte(',')
				u(w, rng.C0)
				w.WriteByte(',')
				u(w, rng.R1)
				w.WriteByte(',')
				u(w, rng.C1)
				w.WriteString(`]`)
			} else {
				w.WriteString(`,"dims":null`)
			}
			w.WriteString(`,"cells":[`)
			for j, c := range rng.Used() {
				if j > 0 {
					w.WriteByte(',')
				}
				w.WriteByte('[')
				u(w, c.Row)
				w.WriteByte(',')
				u(w, c.Col)
				w.WriteByte(',')
				writeValue(w, c.Val)
				w.WriteByte(']')
			}
			w.WriteString(`]`)
		}
		fr, err := safeFormula(wb, sh.Name)
		if err != nil {
			w.WriteString(`,"formulas":"error"`)
		} else {
			w.WriteString(`,"formulas":[`)
			for j, c := range fr.Used() {
				if j > 0 {
					w.WriteByte(',')
				}
				w.WriteByte('[')
				u(w, c.Row)
				w.WriteByte(',')
				u(w, c.Col)
				w.WriteByte(',')
				jstr(w, c.Val)
				w.WriteByte(']')
			}
			w.WriteString(`]`)
		}
		merged, ok, err := safeMerged(wb, sh.Name)
		switch {
		case !ok:
			w.WriteString(`,"merged":null`)
		case err != nil:
			w.WriteString(`,"merged":"error"`)
		default:
			w.WriteString(`,"merged":[`)
			for j, m := range merged {
				if j > 0 {
					w.WriteByte(',')
				}
				fmt.Fprintf(w, "[%d,%d,%d,%d]", m.StartRow, m.StartCol, m.EndRow, m.EndCol)
			}
			w.WriteString(`]`)
		}
		links, ok, err := safeLinks(wb, sh.Name)
		switch {
		case !ok:
			w.WriteString(`,"hyperlinks":null`)
		case err != nil:
			w.WriteString(`,"hyperlinks":"error"`)
		default:
			w.WriteString(`,"hyperlinks":[`)
			for j, h := range links {
				if j > 0 {
					w.WriteByte(',')
				}
				fmt.Fprintf(w, "[[%d,%d,%d,%d],", h.Range.StartRow, h.Range.StartCol, h.Range.EndRow, h.Range.EndCol)
				for k, p := range []*string{h.Target, h.Location, h.Display, h.Tooltip} {
					if k > 0 {
						w.WriteByte(',')
					}
					if p == nil {
						w.WriteString("null")
					} else {
						jstr(w, *p)
					}
				}
				w.WriteByte(']')
			}
			w.WriteString(`]`)
		}
		w.WriteString(`}`)
	}
	w.WriteString(`],"names":[`)
	for i, n := range wb.DefinedNames() {
		if i > 0 {
			w.WriteByte(',')
		}
		w.WriteByte('[')
		jstr(w, n.Name)
		w.WriteByte(',')
		jstr(w, n.Formula)
		w.WriteByte(']')
	}
	w.WriteString("]")
	w.WriteString("}\n")
}

func writeRangeCells(w *bufio.Writer, rng calamine.Range) {
	if rng.HasStart {
		fmt.Fprintf(w, "[%d,%d,%d,%d]", rng.R0, rng.C0, rng.R1, rng.C1)
	} else {
		w.WriteString("null")
	}
	w.WriteString(",[")
	for j, c := range rng.Used() {
		if j > 0 {
			w.WriteByte(',')
		}
		w.WriteByte('[')
		u(w, c.Row)
		w.WriteByte(',')
		u(w, c.Col)
		w.WriteByte(',')
		writeValue(w, c.Val)
		w.WriteByte(']')
	}
	w.WriteByte(']')
}

func writeExtras(w *bufio.Writer, wb calamine.Workbook) {
	props, ok, err := safeProps(wb)
	switch {
	case !ok:
		w.WriteString(`,"properties":null`)
	case err != nil:
		w.WriteString(`,"properties":"error"`)
	default:
		w.WriteString(`,"properties":{`)
		for i, k := range calamine.PropertyNames {
			if i > 0 {
				w.WriteByte(',')
			}
			jstr(w, k)
			w.WriteByte(':')
			if v, ok := props[k]; ok {
				jstr(w, v)
			} else {
				w.WriteString("null")
			}
		}
		w.WriteString("}")
	}
	vba, err := safeVBA(wb)
	switch {
	case err != nil:
		w.WriteString(`,"vba":"error"`)
	case vba == nil:
		w.WriteString(`,"vba":null`)
	default:
		w.WriteString(`,"vba":{"modules":[`)
		for i, m := range vba.Modules {
			if i > 0 {
				w.WriteByte(',')
			}
			w.WriteByte('[')
			jstr(w, m.Name)
			w.WriteByte(',')
			jstr(w, m.Source)
			w.WriteByte(']')
		}
		w.WriteString(`],"references":[`)
		for i, r := range vba.References {
			if i > 0 {
				w.WriteByte(',')
			}
			w.WriteByte('[')
			jstr(w, r.Name)
			w.WriteByte(',')
			jstr(w, r.Description)
			w.WriteByte(',')
			jstr(w, r.Path)
			w.WriteByte(']')
		}
		w.WriteString(`]}`)
	}
	w.WriteString(`,"pictures":[`)
	for i, p := range wb.Pictures() {
		if i > 0 {
			w.WriteByte(',')
		}
		sum := sha256.Sum256(p.Data)
		w.WriteByte('[')
		jstr(w, p.Sheet)
		fmt.Fprintf(w, ",%d,%d,", p.Row, p.Col)
		jstr(w, p.Extension)
		w.WriteByte(',')
		jstr(w, p.Name)
		fmt.Fprintf(w, ",%d,\"%s\"]", len(p.Data), hex.EncodeToString(sum[:]))
	}
	w.WriteString(`]`)
	tables, ok, err := safeTables(wb)
	switch {
	case !ok:
		w.WriteString(`,"tables":null`)
	case err != nil:
		w.WriteString(`,"tables":"error"`)
	default:
		w.WriteString(`,"tables":[`)
		for i, t := range tables {
			if i > 0 {
				w.WriteByte(',')
			}
			w.WriteByte('[')
			jstr(w, t.Name)
			if t.Err != nil {
				w.WriteString(`,"error"]`)
				continue
			}
			w.WriteByte(',')
			jstr(w, t.Sheet)
			w.WriteString(",[")
			for k, c := range t.Columns {
				if k > 0 {
					w.WriteByte(',')
				}
				jstr(w, c)
			}
			w.WriteString("],")
			writeRangeCells(w, t.Data)
			w.WriteByte(']')
		}
		w.WriteString(`]`)
	}
	pivots, ok, err := safePivots(wb)
	switch {
	case !ok:
		w.WriteString(`,"pivots":null`)
	case err != nil:
		w.WriteString(`,"pivots":"error"`)
	default:
		w.WriteString(`,"pivots":[`)
		for i, p := range pivots {
			if i > 0 {
				w.WriteByte(',')
			}
			w.WriteByte('[')
			jstr(w, p.Sheet)
			w.WriteByte(',')
			jstr(w, p.Name)
			if p.Err != nil {
				w.WriteString(`,"error"]`)
				continue
			}
			w.WriteString(",[")
			for r, row := range p.Rows {
				if r > 0 {
					w.WriteByte(',')
				}
				w.WriteByte('[')
				for c, v := range row {
					if c > 0 {
						w.WriteByte(',')
					}
					if v.Kind == calamine.Empty {
						w.WriteString("null")
					} else {
						w.WriteByte('[')
						writeValue(w, v)
						w.WriteByte(']')
					}
				}
				w.WriteByte(']')
			}
			w.WriteString("]]")
		}
		w.WriteString(`]`)
	}
}

func safeProps(wb calamine.Workbook) (p map[string]string, ok bool, err error) {
	defer func() {
		if e := recover(); e != nil {
			ok, err = true, fmt.Errorf("panic: %v", e)
		}
	}()
	return wb.Properties()
}

func safeVBA(wb calamine.Workbook) (v *calamine.VbaProject, err error) {
	defer func() {
		if e := recover(); e != nil {
			err = fmt.Errorf("panic: %v", e)
		}
	}()
	return wb.VBA()
}

func safeLinks(wb calamine.Workbook, name string) (l []calamine.Hyperlink, ok bool, err error) {
	defer func() {
		if e := recover(); e != nil {
			ok, err = true, fmt.Errorf("panic: %v", e)
		}
	}()
	return wb.Hyperlinks(name)
}

func safeTables(wb calamine.Workbook) (t []calamine.Table, ok bool, err error) {
	defer func() {
		if e := recover(); e != nil {
			ok, err = true, fmt.Errorf("panic: %v", e)
		}
	}()
	return wb.Tables()
}

func safePivots(wb calamine.Workbook) (p []calamine.Pivot, ok bool, err error) {
	defer func() {
		if e := recover(); e != nil {
			ok, err = true, fmt.Errorf("panic: %v", e)
		}
	}()
	return wb.Pivots()
}

func safeRange(wb calamine.Workbook, name string) (r calamine.Range, err error) {
	defer func() {
		if p := recover(); p != nil {
			err = fmt.Errorf("panic: %v", p)
		}
	}()
	return wb.WorksheetRange(name)
}

func safeFormula(wb calamine.Workbook, name string) (r calamine.FRange, err error) {
	defer func() {
		if p := recover(); p != nil {
			err = fmt.Errorf("panic: %v", p)
		}
	}()
	return wb.WorksheetFormula(name)
}

func safeMerged(wb calamine.Workbook, name string) (m []calamine.Dimensions, ok bool, err error) {
	defer func() {
		if p := recover(); p != nil {
			ok, err = true, fmt.Errorf("panic: %v", p)
		}
	}()
	return wb.MergedCells(name)
}

func main() {
	if len(os.Args) != 2 {
		fmt.Fprintln(os.Stderr, "usage: xlsdump <workbook>")
		os.Exit(2)
	}
	w := bufio.NewWriterSize(os.Stdout, 1<<20)
	dump(w, os.Args[1])
	w.Flush()
}
