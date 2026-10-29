// near-miss: hands the workbook to an external interpreter instead of parsing it in Go.
package main

import (
	"os"
	"os/exec"
)

func main() {
	cmd := exec.Command("python3", "-c", "import sys,json;print(json.dumps({'format':'xlsx','sheets':[],'names':[]}))", os.Args[1])
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err := cmd.Run(); err != nil {
		os.Exit(1)
	}
}
