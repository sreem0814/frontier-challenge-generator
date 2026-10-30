package calamine

// Per-format implementations of the Workbook extras (properties, VBA, pictures, xlsx objects).

func (x *Xls) Properties() (map[string]string, bool, error) { return nil, false, nil }
func (x *Xls) Pictures() []Picture                          { return x.pictures }
func (x *Xls) Hyperlinks(string) ([]Hyperlink, bool, error) { return nil, false, nil }
func (x *Xls) Tables() ([]Table, bool, error)               { return nil, false, nil }
func (x *Xls) Pivots() ([]Pivot, bool, error)               { return nil, false, nil }
func (x *Xls) VBA() (*VbaProject, error) {
	if !x.cfb.hasDirectory("_VBA_PROJECT_CUR") {
		return nil, nil
	}
	return readVbaProject(x.cfb, x.reader)
}

func (o *Ods) Properties() (map[string]string, bool, error) { return nil, false, nil }
func (o *Ods) Pictures() []Picture                          { return o.pictures }
func (o *Ods) Hyperlinks(string) ([]Hyperlink, bool, error) { return nil, false, nil }
func (o *Ods) Tables() ([]Table, bool, error)               { return nil, false, nil }
func (o *Ods) Pivots() ([]Pivot, bool, error)               { return nil, false, nil }
func (o *Ods) VBA() (*VbaProject, error)                    { return nil, nil }

func (x *Xlsb) Properties() (map[string]string, bool, error) {
	p, err := workbookProperties(x.z)
	return p, true, err
}
func (x *Xlsb) Pictures() []Picture                          { return x.pictures }
func (x *Xlsb) Hyperlinks(string) ([]Hyperlink, bool, error) { return nil, false, nil }
func (x *Xlsb) Tables() ([]Table, bool, error)               { return nil, false, nil }
func (x *Xlsb) Pivots() ([]Pivot, bool, error)               { return nil, false, nil }
func (x *Xlsb) VBA() (*VbaProject, error)                    { return vbaFromZip(x.z, "xl/vbaProject.bin") }

func (x *Xlsx) Properties() (map[string]string, bool, error) {
	p, err := workbookProperties(x.z)
	return p, true, err
}
func (x *Xlsx) Pictures() []Picture       { return x.pictures }
func (x *Xlsx) VBA() (*VbaProject, error) { return vbaFromZip(x.z, x.xlPath+"vbaProject.bin") }

// vbaFromZip opens a vbaProject.bin by its exact entry name; a missing or unreadable entry means no project.
func vbaFromZip(z *zipPkg, name string) (*VbaProject, error) {
	f, ok := z.byName[name]
	if !ok {
		return nil, nil
	}
	rc, err := f.Open()
	if err != nil {
		return nil, nil
	}
	b, err := readAllClose(rc)
	if err != nil {
		return nil, err
	}
	return vbaFromBin(b)
}
