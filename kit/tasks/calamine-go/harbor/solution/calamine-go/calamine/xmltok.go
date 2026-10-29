package calamine

// A small pull XML tokenizer with the event model calamine relies on
// (quick-xml with expand_empty_elements, no end-name checks, untrimmed text).

import (
	"bytes"
	"errors"
	"strconv"
	"strings"
	"unicode/utf8"
)

type evKind int

const (
	evEOF evKind = iota
	evStart
	evEnd
	evText
	evRef
	evCData
	evComment
	evPI
	evDecl
	evDocType
)

type xmlEvent struct {
	kind  evKind
	name  []byte // element name (raw, with prefix) for start/end
	attrs []byte // raw attribute bytes for start events
	text  []byte // raw text / ref name / cdata content
}

func (e *xmlEvent) localName() []byte {
	if i := bytes.LastIndexByte(e.name, ':'); i >= 0 {
		return e.name[i+1:]
	}
	return e.name
}

func (e *xmlEvent) isLocal(n string) bool { return string(e.localName()) == n }
func (e *xmlEvent) isName(n string) bool  { return string(e.name) == n }

type xmlReader struct {
	buf        []byte
	pos        int
	pendingEnd []byte // expand_empty_elements: End event owed after an empty element
	hasPending bool
}

func newXMLReader(b []byte) *xmlReader {
	if len(b) >= 3 && b[0] == 0xEF && b[1] == 0xBB && b[2] == 0xBF {
		b = b[3:]
	}
	return &xmlReader{buf: b}
}

var errXMLSyntax = errors.New("xml syntax error")

func (r *xmlReader) next() (xmlEvent, error) {
	ev, err := r.next0()
	if err != nil {
		return ev, err
	}
	if !utf8.Valid(ev.text) || !utf8.Valid(ev.name) || !utf8.Valid(ev.attrs) {
		return xmlEvent{}, errors.New("invalid utf-8 in xml")
	}
	return ev, nil
}

func (r *xmlReader) next0() (xmlEvent, error) {
	if r.hasPending {
		r.hasPending = false
		return xmlEvent{kind: evEnd, name: r.pendingEnd}, nil
	}
	b := r.buf
	if r.pos >= len(b) {
		return xmlEvent{kind: evEOF}, nil
	}
	c := b[r.pos]
	if c == '&' {
		end := bytes.IndexByte(b[r.pos:], ';')
		if end < 0 {
			return xmlEvent{}, errXMLSyntax
		}
		name := b[r.pos+1 : r.pos+end]
		r.pos += end + 1
		return xmlEvent{kind: evRef, text: name}, nil
	}
	if c != '<' {
		start := r.pos
		for r.pos < len(b) && b[r.pos] != '<' && b[r.pos] != '&' {
			r.pos++
		}
		return xmlEvent{kind: evText, text: b[start:r.pos]}, nil
	}
	// markup
	rest := b[r.pos:]
	switch {
	case bytes.HasPrefix(rest, []byte("<!--")):
		end := bytes.Index(rest[4:], []byte("-->"))
		if end < 0 {
			return xmlEvent{}, errXMLSyntax
		}
		txt := rest[4 : 4+end]
		r.pos += 4 + end + 3
		return xmlEvent{kind: evComment, text: txt}, nil
	case bytes.HasPrefix(rest, []byte("<![CDATA[")):
		end := bytes.Index(rest[9:], []byte("]]>"))
		if end < 0 {
			return xmlEvent{}, errXMLSyntax
		}
		txt := rest[9 : 9+end]
		r.pos += 9 + end + 3
		return xmlEvent{kind: evCData, text: txt}, nil
	case bytes.HasPrefix(rest, []byte("<!")):
		// DOCTYPE (may contain an internal subset in brackets)
		depth := 0
		i := 2
		for ; i < len(rest); i++ {
			switch rest[i] {
			case '[':
				depth++
			case ']':
				depth--
			case '>':
				if depth <= 0 {
					r.pos += i + 1
					return xmlEvent{kind: evDocType, text: rest[2:i]}, nil
				}
			}
		}
		return xmlEvent{}, errXMLSyntax
	case bytes.HasPrefix(rest, []byte("<?")):
		end := bytes.Index(rest[2:], []byte("?>"))
		if end < 0 {
			return xmlEvent{}, errXMLSyntax
		}
		txt := rest[2 : 2+end]
		r.pos += 2 + end + 2
		if bytes.HasPrefix(txt, []byte("xml")) && (len(txt) == 3 || isXMLSpace(txt[3])) {
			return xmlEvent{kind: evDecl, text: txt}, nil
		}
		return xmlEvent{kind: evPI, text: txt}, nil
	case len(rest) > 1 && rest[1] == '/':
		end := bytes.IndexByte(rest, '>')
		if end < 0 {
			return xmlEvent{}, errXMLSyntax
		}
		name := bytes.TrimRight(rest[2:end], " \t\r\n")
		r.pos += end + 1
		return xmlEvent{kind: evEnd, name: name}, nil
	}
	// start tag: find the closing '>' outside quotes
	i := 1
	var q byte
	for ; i < len(rest); i++ {
		ch := rest[i]
		if q != 0 {
			if ch == q {
				q = 0
			}
			continue
		}
		if ch == '"' || ch == '\'' {
			q = ch
			continue
		}
		if ch == '>' {
			break
		}
	}
	if i >= len(rest) {
		return xmlEvent{}, errXMLSyntax
	}
	content := rest[1:i]
	r.pos += i + 1
	empty := false
	if len(content) > 0 && content[len(content)-1] == '/' {
		empty = true
		content = content[:len(content)-1]
	}
	n := 0
	for n < len(content) && !isXMLSpace(content[n]) {
		n++
	}
	ev := xmlEvent{kind: evStart, name: content[:n], attrs: content[n:]}
	if empty {
		r.pendingEnd = ev.name
		r.hasPending = true
	}
	return ev, nil
}

func isXMLSpace(c byte) bool { return c == ' ' || c == '\t' || c == '\r' || c == '\n' }

// readToEnd skips to the End event matching name (nesting-aware), like quick-xml read_to_end.
func (r *xmlReader) readToEnd(name []byte) error {
	depth := 0
	for {
		ev, err := r.next()
		if err != nil {
			return err
		}
		switch ev.kind {
		case evEOF:
			return errors.New("unexpected eof")
		case evStart:
			if bytes.Equal(ev.name, name) {
				depth++
			}
		case evEnd:
			if bytes.Equal(ev.name, name) {
				if depth == 0 {
					return nil
				}
				depth--
			}
		}
	}
}

// ---- attributes (calamine's RawAttrIter) ----

type rawAttr struct{ key, val string }

func iterAttrs(raw []byte, fn func(k, v string) bool) error {
	s := string(raw)
	pos := 0
	n := len(s)
	for {
		for pos < n && isASCIISpace(s[pos]) {
			pos++
		}
		if pos >= n {
			return nil
		}
		ks := pos
		for pos < n && s[pos] != '=' {
			pos++
		}
		if pos >= n {
			return errors.New("attribute without '='")
		}
		key := strings.TrimRight(s[ks:pos], " \t\r\n\f")
		pos++
		for pos < n && isASCIISpace(s[pos]) {
			pos++
		}
		if pos >= n || (s[pos] != '"' && s[pos] != '\'') {
			return errors.New("unquoted attribute value")
		}
		q := s[pos]
		pos++
		vs := pos
		for pos < n && s[pos] != q {
			pos++
		}
		val := s[vs:pos]
		if pos < n {
			pos++
		}
		if !fn(key, val) {
			return nil
		}
	}
}

func isASCIISpace(c byte) bool {
	return c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '\f'
}

// rawAttrLookup returns the first attribute whose raw key equals name.
func rawAttrLookup(raw []byte, name string) (string, bool, error) {
	var out string
	found := false
	err := iterAttrs(raw, func(k, v string) bool {
		if k == name {
			out, found = v, true
			return false
		}
		return true
	})
	if found {
		return out, true, nil
	}
	return "", false, err
}

// getAttrs mirrors calamine's get_attrs! macro: first value for each key; stops once all are found.
func getAttrs(raw []byte, keys ...string) ([]string, []bool, error) {
	vals := make([]string, len(keys))
	has := make([]bool, len(keys))
	found := 0
	err := iterAttrs(raw, func(k, v string) bool {
		for i, key := range keys {
			if k == key {
				vals[i] = v
				if !has[i] {
					has[i] = true
				}
				found++
				break
			}
		}
		return found != len(keys)
	})
	return vals, has, err
}

func localNameMatches(key, local string) bool {
	if key == local {
		return true
	}
	if strings.HasSuffix(key, local) {
		p := key[:len(key)-len(local)]
		return len(p) > 0 && p[len(p)-1] == ':'
	}
	return false
}

// ---- entity handling ----

func resolveEntity(name string) (string, bool) {
	switch name {
	case "lt":
		return "<", true
	case "gt":
		return ">", true
	case "amp":
		return "&", true
	case "apos":
		return "'", true
	case "quot":
		return "\"", true
	}
	return "", false
}

func resolveCharRef(name string) (string, bool, error) {
	if !strings.HasPrefix(name, "#") {
		return "", false, nil
	}
	num := name[1:]
	var v uint64
	var err error
	if strings.HasPrefix(num, "x") {
		v, err = strconv.ParseUint(num[1:], 16, 32)
	} else {
		v, err = strconv.ParseUint(num, 10, 32)
	}
	if err != nil || v == 0 || v > 0x10FFFF || (v >= 0xD800 && v <= 0xDFFF) {
		return "", true, errors.New("invalid character reference")
	}
	return string(rune(v)), true, nil
}

// unescapeRef resolves the content of a GeneralRef event (calamine unescape_entity_to_buffer).
func unescapeRef(name []byte, sb *strings.Builder) error {
	n := string(name)
	if s, ok := resolveEntity(n); ok {
		sb.WriteString(s)
		return nil
	}
	s, ok, err := resolveCharRef(n)
	if err != nil {
		return err
	}
	if ok {
		sb.WriteString(s)
		return nil
	}
	return errors.New("unrecognized entity &" + n + ";")
}

// decodeAttr is quick_xml::escape::unescape.
func decodeAttr(v string) (string, error) {
	if strings.IndexByte(v, '&') < 0 {
		return v, nil
	}
	var sb strings.Builder
	i := 0
	for i < len(v) {
		c := v[i]
		if c != '&' {
			sb.WriteByte(c)
			i++
			continue
		}
		end := strings.IndexByte(v[i:], ';')
		if end < 0 {
			return "", errors.New("unterminated entity")
		}
		if err := unescapeRef([]byte(v[i+1:i+end]), &sb); err != nil {
			return "", err
		}
		i += end + 1
	}
	return sb.String(), nil
}

// xml10Content decodes text as UTF-8 and normalizes XML 1.0 end-of-lines.
func xml10Content(b []byte) (string, error) {
	if !utf8.Valid(b) {
		return "", errors.New("invalid utf-8 in xml text")
	}
	if bytes.IndexByte(b, '\r') < 0 {
		return string(b), nil
	}
	out := make([]byte, 0, len(b))
	for i := 0; i < len(b); i++ {
		if b[i] == '\r' {
			out = append(out, '\n')
			if i+1 < len(b) && b[i+1] == '\n' {
				i++
			}
			continue
		}
		out = append(out, b[i])
	}
	return string(out), nil
}
