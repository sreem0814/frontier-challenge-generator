// Alternative CLI for the l3 alt-solution variant: same library, different JSON writer
// (encoding/json, indented, objects built from maps, floats as 'e'-formatted json.Number).
package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"math"
	"os"
	"strconv"

	"calaminego/calamine"
)

func num(f float64) any {
	switch {
	case math.IsNaN(f):
		return "NaN"
	case math.IsInf(f, 1):
		return "inf"
	case math.IsInf(f, -1):
		return "-inf"
	}
	return json.Number(strconv.FormatFloat(f, 'e', -1, 64))
}

func value(d calamine.Data) []any {
	switch d.Kind {
	case calamine.Int:
		return []any{"i", d.I}
	case calamine.Float:
		return []any{"f", num(d.F)}
	case calamine.String:
		return []any{"s", d.S}
	case calamine.Bool:
		return []any{"b", d.B}
	case calamine.DateTime:
		k := "datetime"
		if d.DT == calamine.DTTimeDelta {
			k = "timedelta"
		}
		return []any{"d", num(d.F), k, calamine.FormatDateTime(d.F, d.Is1904)}
	case calamine.DateTimeIso:
		return []any{"di", d.S}
	case calamine.DurationIso:
		return []any{"du", d.S}
	case calamine.Error:
		return []any{"e", d.E.String()}
	}
	return nil
}

func main() {
	wb, err := calamine.Open(os.Args[1])
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	enc.SetEscapeHTML(false)
	if err != nil {
		enc.Encode(map[string]any{"detail": err.Error(), "error": "open"})
		return
	}
	var sheets []any
	for _, sh := range wb.Sheets() {
		m := map[string]any{"visible": sh.Visible.String(), "type": sh.Type.String(), "name": sh.Name}
		if r, err := wb.WorksheetRange(sh.Name); err != nil {
			m["cells"], m["dims"] = "error", nil
		} else {
			if r.HasStart {
				m["dims"] = []uint32{r.R0, r.C0, r.R1, r.C1}
			} else {
				m["dims"] = nil
			}
			cells := []any{}
			for _, c := range r.Used() {
				cells = append(cells, append([]any{c.Row, c.Col}, value(c.Val)...))
			}
			m["cells"] = cells
		}
		if fr, err := wb.WorksheetFormula(sh.Name); err != nil {
			m["formulas"] = "error"
		} else {
			fs := []any{}
			for _, c := range fr.Used() {
				fs = append(fs, []any{c.Row, c.Col, c.Val})
			}
			m["formulas"] = fs
		}
		if mc, ok, err := wb.MergedCells(sh.Name); !ok {
			m["merged"] = nil
		} else if err != nil {
			m["merged"] = "error"
		} else {
			ms := []any{}
			for _, d := range mc {
				ms = append(ms, []uint32{d.StartRow, d.StartCol, d.EndRow, d.EndCol})
			}
			m["merged"] = ms
		}
		if hl, ok, err := wb.Hyperlinks(sh.Name); !ok {
			m["hyperlinks"] = nil
		} else if err != nil {
			m["hyperlinks"] = "error"
		} else {
			hs := []any{}
			for _, h := range hl {
				hs = append(hs, []any{[]uint32{h.Range.StartRow, h.Range.StartCol, h.Range.EndRow, h.Range.EndCol},
					h.Target, h.Location, h.Display, h.Tooltip})
			}
			m["hyperlinks"] = hs
		}
		sheets = append(sheets, m)
	}
	names := []any{}
	for _, n := range wb.DefinedNames() {
		names = append(names, []string{n.Name, n.Formula})
	}
	if sheets == nil {
		sheets = []any{}
	}
	out := map[string]any{"names": names, "sheets": sheets, "format": wb.Format()}
	if p, ok, err := wb.Properties(); !ok {
		out["properties"] = nil
	} else if err != nil {
		out["properties"] = "error"
	} else {
		pm := map[string]any{}
		for _, k := range calamine.PropertyNames {
			if v, ok := p[k]; ok {
				pm[k] = v
			} else {
				pm[k] = nil
			}
		}
		out["properties"] = pm
	}
	if v, err := wb.VBA(); err != nil {
		out["vba"] = "error"
	} else if v == nil {
		out["vba"] = nil
	} else {
		mods := [][]string{}
		for _, md := range v.Modules {
			mods = append(mods, []string{md.Name, md.Source})
		}
		refs := [][]string{}
		for _, r := range v.References {
			refs = append(refs, []string{r.Name, r.Description, r.Path})
		}
		out["vba"] = map[string]any{"references": refs, "modules": mods}
	}
	pics := []any{}
	ps := wb.Pictures()
	for i := len(ps) - 1; i >= 0; i-- { // reverse order: pictures are compared as a multiset
		p := ps[i]
		sum := sha256.Sum256(p.Data)
		pics = append(pics, []any{p.Sheet, p.Row, p.Col, p.Extension, p.Name, len(p.Data), hex.EncodeToString(sum[:])})
	}
	out["pictures"] = pics
	if ts, ok, err := wb.Tables(); !ok {
		out["tables"] = nil
	} else if err != nil {
		out["tables"] = "error"
	} else {
		arr := []any{}
		for _, t := range ts {
			if t.Err != nil {
				arr = append(arr, []any{t.Name, "error"})
				continue
			}
			var dims any
			if t.Data.HasStart {
				dims = []uint32{t.Data.R0, t.Data.C0, t.Data.R1, t.Data.C1}
			}
			cells := []any{}
			for _, c := range t.Data.Used() {
				cells = append(cells, append([]any{c.Row, c.Col}, value(c.Val)...))
			}
			cols := t.Columns
			if cols == nil {
				cols = []string{}
			}
			arr = append(arr, []any{t.Name, t.Sheet, cols, dims, cells})
		}
		out["tables"] = arr
	}
	if pv, ok, err := wb.Pivots(); !ok {
		out["pivots"] = nil
	} else if err != nil {
		out["pivots"] = "error"
	} else {
		arr := []any{}
		for _, p := range pv {
			if p.Err != nil {
				arr = append(arr, []any{p.Sheet, p.Name, "error"})
				continue
			}
			rows := []any{}
			for _, row := range p.Rows {
				vals := []any{}
				for _, v := range row {
					if v.Kind == calamine.Empty {
						vals = append(vals, nil)
					} else {
						vals = append(vals, value(v))
					}
				}
				rows = append(rows, vals)
			}
			arr = append(arr, []any{p.Sheet, p.Name, rows})
		}
		out["pivots"] = arr
	}
	if err := enc.Encode(out); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
