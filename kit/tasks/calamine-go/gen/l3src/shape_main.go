// near-miss: the right data in the wrong JSON shape (cells as objects, sheets keyed by name).
package main

import (
	"encoding/json"
	"os"

	"calaminego/calamine"
)

func main() {
	wb, err := calamine.Open(os.Args[1])
	if err != nil {
		os.Exit(1)
	}
	out := map[string]any{}
	for _, sh := range wb.Sheets() {
		r, _ := wb.WorksheetRange(sh.Name)
		var cells []map[string]any
		for _, c := range r.Used() {
			cells = append(cells, map[string]any{"row": c.Row, "col": c.Col, "kind": int(c.Val.Kind), "s": c.Val.S, "f": c.Val.F, "i": c.Val.I})
		}
		out[sh.Name] = cells
	}
	json.NewEncoder(os.Stdout).Encode(map[string]any{"workbook": out})
}
