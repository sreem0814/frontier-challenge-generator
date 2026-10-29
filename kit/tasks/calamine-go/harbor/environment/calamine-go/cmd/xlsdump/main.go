// Command xlsdump reads one workbook (.xls, .xlsx, .xlsm, .xlsb or .ods) and prints it as JSON
// on stdout. The output format is specified in the task description ("Output format").
//
// Usage: xlsdump <path-to-workbook>
package main

import (
	"fmt"
	"os"
)

func main() {
	if len(os.Args) != 2 {
		fmt.Fprintln(os.Stderr, "usage: xlsdump <workbook>")
		os.Exit(2)
	}
	fmt.Fprintln(os.Stderr, "xlsdump: not implemented")
	os.Exit(1)
}
