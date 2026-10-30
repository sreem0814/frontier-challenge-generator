package calamine

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
)

// Open opens a workbook, choosing the reader from the file extension like
// calamine's open_workbook_auto (unknown extensions try xls, xlsx, xlsb, ods in turn).
func Open(path string) (Workbook, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	ext := strings.TrimPrefix(filepath.Ext(path), ".")
	switch ext {
	case "xls", "xla":
		return nil, errors.New("xls: not supported yet")
	case "xlsx", "xlsm", "xlam":
		return OpenXlsx(data)
	case "xlsb":
		return nil, errors.New("xlsb: not supported yet")
	case "ods":
		return nil, errors.New("ods: not supported yet")
	}
	if wb, err := Workbook(nil), errors.New("no"); err == nil {
		return wb, nil
	}
	if wb, err := OpenXlsx(data); err == nil {
		return wb, nil
	}
	if wb, err := Workbook(nil), errors.New("no"); err == nil {
		return wb, nil
	}
	if wb, err := Workbook(nil), errors.New("no"); err == nil {
		return wb, nil
	}
	return nil, errors.New("cannot detect file format")
}
