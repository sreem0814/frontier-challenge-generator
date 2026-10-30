package calamine

// Embedded pictures (calamine's "picture" feature): OfficeArt blips in xls, DrawingML anchors and
// rich-data images in xlsx, media files in xlsb and ods.

import (
	"bytes"
	"errors"
	"strconv"
	"strings"
)

// Picture is an embedded image. Only xlsx fills Sheet, Row, Col and Name.
type Picture struct {
	Sheet     string
	Row, Col  uint32
	Extension string
	Name      string
	Data      []byte
}

var pictureExts = map[string]bool{"emf": true, "wmf": true, "pict": true, "jpeg": true, "jpg": true,
	"png": true, "dib": true, "gif": true, "tiff": true, "eps": true, "bmp": true, "wpg": true}

func lastDotPart(name string) string {
	if i := strings.LastIndexByte(name, '.'); i >= 0 {
		return name[i+1:]
	}
	return name
}

// zipMediaPictures scans the archive in entry order for media under prefix (xlsb, ods).
func zipMediaPictures(z *zipPkg, prefix string) ([]Picture, error) {
	var pics []Picture
	for _, f := range z.zr.File {
		if !strings.HasPrefix(f.Name, prefix) {
			continue
		}
		ext := lastDotPart(f.Name)
		if !pictureExts[ext] {
			continue
		}
		rc, err := f.Open()
		if err != nil {
			return nil, err
		}
		b, err := readAllClose(rc)
		if err != nil {
			return nil, err
		}
		pics = append(pics, Picture{Extension: ext, Data: b})
	}
	return pics, nil
}

// ---- xls: OfficeArt records in the MsoDrawingGroup stream ----

func parseArtPictures(stream []byte) ([]Picture, error) {
	var pics []Picture
	for len(stream) > 0 {
		if len(stream) < 8 {
			return nil, errors.New("end of stream: art record header")
		}
		verIns := u16(stream)
		instance := verIns >> 4
		typ := u16(stream[2:])
		if typ < 0xF000 {
			return nil, errors.New("invalid art record: type range 0xF000 - 0xFFFF")
		}
		l := int(u32(stream[4:]))
		if len(stream) < l+8 {
			return nil, errors.New("end of stream: art record length")
		}
		data := stream[8 : 8+l]
		stream = stream[8+l:]
		switch typ {
		case 0xF000, 0xF001:
			sub, err := parseArtPictures(data)
			if err != nil {
				return nil, err
			}
			pics = append(pics, sub...)
		case 0xF007:
			skip := 36 + int(data[33])
			sub, err := parseArtPictures(data[skip:])
			if err != nil {
				return nil, err
			}
			pics = append(pics, sub...)
		case 0xF01A, 0xF01B, 0xF01C, 0xF01D, 0xF01E, 0xF01F, 0xF029, 0xF02A:
			var ext string
			var skip int
			pick := func(e string, a uint16, sa int, b uint16, sb int) {
				ext = e
				switch instance {
				case a:
					skip = sa
				case b:
					skip = sb
				default:
					panic("unreachable blip instance")
				}
			}
			switch typ {
			case 0xF01A:
				pick("emf", 0x3D4, 50, 0x3D5, 66)
			case 0xF01B:
				pick("wmf", 0x216, 50, 0x217, 66)
			case 0xF01C:
				pick("pict", 0x542, 50, 0x543, 66)
			case 0xF01D, 0xF02A:
				ext = "jpg"
				switch instance {
				case 0x46A, 0x6E2:
					skip = 17
				case 0x46B, 0x6E3:
					skip = 33
				default:
					panic("unreachable blip instance")
				}
			case 0xF01E:
				pick("png", 0x6E0, 17, 0x6E1, 33)
			case 0xF01F:
				pick("dib", 0x7A8, 17, 0x7A9, 33)
			case 0xF029:
				pick("tiff", 0x6E4, 17, 0x6E5, 33)
			}
			pics = append(pics, Picture{Extension: ext, Data: append([]byte(nil), data[skip:]...)})
		}
	}
	return pics, nil
}

// ---- xlsx ----

func resolvePath(base, target string) string {
	if strings.HasPrefix(target, "/") {
		return target[1:]
	}
	if rel, ok := strings.CutPrefix(target, "../"); ok {
		parent := ""
		if i := strings.LastIndexByte(base, '/'); i >= 0 {
			parent = base[:i]
		}
		return parent + "/" + rel
	}
	return base + "/" + target
}

func colFromCellRef(ref string) uint32 {
	var col uint32
	for i := 0; i < len(ref); i++ {
		b := ref[i]
		if isASCIILetter(b) {
			u := b
			if u >= 'a' {
				u -= 32
			}
			col = col*26 + uint32(u-'A') + 1
		} else {
			break
		}
	}
	if col == 0 {
		return 0
	}
	return col - 1
}

// rustParseU32 is str::parse::<u32> (an optional '+', digits, no overflow).
func rustParseU32(s string) (uint32, bool) {
	t := strings.TrimPrefix(s, "+")
	if t == "" {
		return 0, false
	}
	var v uint64
	for i := 0; i < len(t); i++ {
		if t[i] < '0' || t[i] > '9' {
			return 0, false
		}
		v = v*10 + uint64(t[i]-'0')
		if v > 0xFFFFFFFF {
			return 0, false
		}
	}
	return uint32(v), true
}

type mediaEntry struct {
	ext  string
	data []byte
}

// rustTrim is str::trim (Unicode White_Space).
func rustTrim(s string) string { return strings.TrimSpace(s) }

func (x *Xlsx) relsTargets(relPath string, want func(typ string) bool, withID bool) (map[string]string, []string, bool, error) {
	xr, err := x.z.xml(relPath)
	if err == errZipNotFound {
		return nil, nil, false, nil
	} else if err != nil {
		return nil, nil, true, err
	}
	ids := map[string]string{}
	var list []string
	for {
		ev, err := xr.next()
		if err != nil || ev.kind == evEOF {
			break // errors end the scan silently, like calamine
		}
		if ev.kind == evStart && ev.isLocal("Relationship") {
			v, has, err := getAttrs(ev.attrs, "Id", "Target", "Type")
			if err != nil {
				return nil, nil, true, err
			}
			if !has[2] || !want(v[2]) {
				continue
			}
			if withID {
				if !has[0] {
					continue
				}
				id, err := decodeAttr(v[0])
				if err != nil {
					return nil, nil, true, err
				}
				if id == "" {
					continue
				}
				t := ""
				if has[1] {
					if t, err = decodeAttr(v[1]); err != nil {
						return nil, nil, true, err
					}
				}
				ids[id] = t
			} else if has[1] {
				t, err := decodeAttr(v[1])
				if err != nil {
					return nil, nil, true, err
				}
				if t != "" {
					list = append(list, t)
				}
			}
		} else if ev.kind == evEnd && ev.isLocal("Relationships") {
			break
		}
	}
	return ids, list, true, nil
}

func (x *Xlsx) readPictures() error {
	media := map[string]mediaEntry{}
	mediaPath := x.xlPath + "media"
	for _, f := range x.z.zr.File {
		if !strings.HasPrefix(f.Name, mediaPath) {
			continue
		}
		ext := lastDotPart(f.Name)
		if !pictureExts[ext] {
			continue
		}
		rc, err := f.Open()
		if err != nil {
			return err
		}
		b, err := readAllClose(rc)
		if err != nil {
			return err
		}
		media[asciiLower(f.Name)] = mediaEntry{ext, b}
	}
	if len(media) == 0 {
		return nil
	}
	var pics []Picture
	seen := map[string]bool{}
	for _, sh := range x.sheets {
		slash := strings.LastIndexByte(sh.path, '/')
		if slash < 0 {
			slash = 0
		}
		base, file := sh.path[:slash], sh.path[slash:]
		_, drawings, ok, err := x.relsTargets(base+"/_rels"+file+".rels",
			func(t string) bool { return strings.HasSuffix(t, "/drawing") }, false)
		if err != nil {
			return err
		}
		if !ok {
			continue
		}
		for _, d := range drawings {
			dpath := resolvePath(base, d)
			ds := strings.LastIndexByte(dpath, '/')
			if ds < 0 {
				ds = 0
			}
			dbase, dfile := dpath[:ds], dpath[ds:]
			ridTarget, _, ok, err := x.relsTargets(dbase+"/_rels"+dfile+".rels",
				func(t string) bool { return strings.HasSuffix(t, "/image") }, true)
			if err != nil {
				return err
			}
			if !ok {
				continue
			}
			ridToMedia := map[string]string{}
			for id, t := range ridTarget {
				ridToMedia[id] = asciiLower(resolvePath(dbase, t))
			}
			xr, err := x.z.xml(dpath)
			if err == errZipNotFound {
				continue
			} else if err != nil {
				return err
			}
			inAnchor, inFrom, inCol, inRow := false, false, false, false
			var row, col uint32
			name, rid := "", ""
			for {
				ev, err := xr.next()
				if err != nil {
					return err
				}
				if ev.kind == evEOF {
					break
				}
				switch ev.kind {
				case evStart:
					switch string(ev.localName()) {
					case "twoCellAnchor", "oneCellAnchor", "absoluteAnchor":
						inAnchor = true
						row, col = 0, 0
						name, rid = "", ""
					case "from":
						if inAnchor {
							inFrom = true
						}
					case "col":
						if inFrom {
							inCol = true
						}
					case "row":
						if inFrom {
							inRow = true
						}
					case "blip":
						if inAnchor {
							var v string
							found := false
							err := iterAttrs(ev.attrs, func(k, val string) bool {
								if localNameMatches(k, "embed") {
									v, found = val, true
									return false
								}
								return true
							})
							if !found && err != nil {
								return err
							}
							if found {
								if rid, err = decodeAttr(v); err != nil {
									return err
								}
							}
						}
					case "cNvPr":
						if inAnchor {
							v, ok, err := rawAttrLookup(ev.attrs, "name")
							if err != nil {
								return err
							}
							if ok {
								if name, err = decodeAttr(v); err != nil {
									return err
								}
							}
						}
					}
				case evEnd:
					switch string(ev.localName()) {
					case "twoCellAnchor", "oneCellAnchor", "absoluteAnchor":
						if rid != "" {
							if mp, ok := ridToMedia[rid]; ok {
								if m, ok := media[mp]; ok {
									seen[mp] = true
									pics = append(pics, Picture{Sheet: sh.name, Row: row, Col: col,
										Extension: m.ext, Name: name, Data: m.data})
								}
							}
						}
						inAnchor = false
					case "from":
						inFrom = false
					case "col":
						inCol = false
					case "row":
						inRow = false
					}
				case evText:
					t, err := xml10Content(ev.text)
					if err != nil {
						return err
					}
					if inCol {
						v, _ := rustParseU32(rustTrim(t))
						col = v
					} else if inRow {
						v, _ := rustParseU32(rustTrim(t))
						row = v
					}
				}
			}
		}
	}
	rich, err := x.readRichDataPictures(media, seen)
	if err != nil {
		return err
	}
	pics = append(pics, rich...)
	for p, m := range media {
		if !seen[p] {
			pics = append(pics, Picture{Extension: m.ext, Data: m.data})
		}
	}
	x.pictures = pics
	return nil
}

func (x *Xlsx) readRichDataPictures(media map[string]mediaEntry, seen map[string]bool) ([]Picture, error) {
	ids, _, ok, err := x.relsTargets("xl/richData/_rels/richValueRel.xml.rels",
		func(t string) bool { return strings.HasSuffix(t, "/image") }, true)
	if err != nil || !ok {
		return nil, err
	}
	ridToMedia := map[string]string{}
	for id, t := range ids {
		ridToMedia[id] = asciiLower(resolvePath("xl/richData", t))
	}
	if len(ridToMedia) == 0 {
		return nil, nil
	}
	var idxToMedia []string
	xr, err := x.z.xml("xl/richData/richValueRel.xml")
	if err == errZipNotFound {
		return nil, nil
	} else if err != nil {
		return nil, err
	}
	for {
		ev, err := xr.next()
		if err != nil || ev.kind == evEOF {
			break
		}
		if ev.kind == evStart && ev.isLocal("rel") {
			rid := ""
			var v string
			found := false
			aerr := iterAttrs(ev.attrs, func(k, val string) bool {
				if localNameMatches(k, "id") {
					v, found = val, true
					return false
				}
				return true
			})
			if !found && aerr != nil {
				return nil, aerr
			}
			if found {
				if rid, err = decodeAttr(v); err != nil {
					return nil, err
				}
			}
			idxToMedia = append(idxToMedia, ridToMedia[rid])
		}
	}
	if len(idxToMedia) == 0 {
		return nil, nil
	}
	rvToImg := map[int]int{}
	xr, err = x.z.xml("xl/richData/rdrichvalue.xml")
	if err == errZipNotFound {
		return nil, nil
	} else if err != nil {
		return nil, err
	}
	rv, vcount, img := 0, 0, 0
	inRv, inV := false, false
	for {
		ev, err := xr.next()
		if err != nil || ev.kind == evEOF {
			break
		}
		switch {
		case ev.kind == evStart && ev.isLocal("rv"):
			inRv, vcount, img = true, 0, 0
		case ev.kind == evStart && inRv && ev.isLocal("v"):
			inV = true
		case ev.kind == evText && inV && vcount == 0:
			t, err := xml10Content(ev.text)
			if err != nil {
				return nil, err
			}
			n, ok := rustParseUsize2(rustTrim(t))
			if !ok {
				n = 0
			}
			img = n
		case ev.kind == evEnd && ev.isLocal("v"):
			inV = false
			vcount++
		case ev.kind == evEnd && ev.isLocal("rv"):
			rvToImg[rv] = img
			rv++
			inRv = false
		}
	}
	if len(rvToImg) == 0 {
		return nil, nil
	}
	var pics []Picture
	for _, sh := range x.sheets {
		xr, err := x.z.xml(sh.path)
		if err == errZipNotFound {
			continue
		} else if err != nil {
			return nil, err
		}
		var curRow uint32
		for {
			ev, err := xr.next()
			if err != nil {
				return nil, err
			}
			if ev.kind == evEOF {
				break
			}
			if ev.kind != evStart {
				continue
			}
			if ev.isLocal("row") {
				v, ok, err := rawAttrLookup(ev.attrs, "r")
				if err != nil {
					return nil, err
				}
				if ok {
					n, ok := atoiU32(v)
					if !ok {
						n = 1
					}
					curRow = n - 1 // wraps like the Rust release build
				}
			} else if ev.isLocal("c") {
				v, has, err := getAttrs(ev.attrs, "vm", "r")
				if err != nil {
					return nil, err
				}
				if !has[0] {
					continue
				}
				vm, ok := atoiUsize(v[0])
				if !ok {
					continue
				}
				rvIdx := vm - 1
				if vm == 0 {
					rvIdx = 0
				}
				imgIdx, ok := rvToImg[rvIdx]
				if !ok || imgIdx >= len(idxToMedia) {
					continue
				}
				mp := idxToMedia[imgIdx]
				if mp == "" {
					continue
				}
				m, ok := media[mp]
				if !ok {
					continue
				}
				col := uint32(0)
				if has[1] {
					col = colFromCellRef(v[1])
				}
				seen[mp] = true
				pics = append(pics, Picture{Sheet: sh.name, Row: curRow, Col: col, Extension: m.ext, Data: m.data})
			}
		}
	}
	return pics, nil
}

// atoiU32 is atoi_simd::parse::<u32, true, false>.
func atoiU32(s string) (uint32, bool) {
	v, ok := atoiUsize(s)
	if !ok || v > 0xFFFFFFFF {
		return 0, false
	}
	return uint32(v), true
}

// rustParseUsize2 is str::parse::<usize> returning ok=false on failure.
func rustParseUsize2(s string) (int, bool) {
	v, err := rustParseUsize(s)
	return v, err == nil
}

func readAllClose(rc interface {
	Read([]byte) (int, error)
	Close() error
}) ([]byte, error) {
	defer rc.Close()
	var buf bytes.Buffer
	_, err := buf.ReadFrom(rc)
	return buf.Bytes(), err
}

var _ = strconv.Itoa
