// Package textdeps pins the golang.org/x/text packages that are vendored in this module.
// They are the only third-party code available offline. Import what you need from them directly.
package textdeps

import (
	_ "golang.org/x/text/encoding"
	_ "golang.org/x/text/encoding/charmap"
	_ "golang.org/x/text/encoding/htmlindex"
	_ "golang.org/x/text/encoding/japanese"
	_ "golang.org/x/text/encoding/korean"
	_ "golang.org/x/text/encoding/simplifiedchinese"
	_ "golang.org/x/text/encoding/traditionalchinese"
	_ "golang.org/x/text/encoding/unicode"
	_ "golang.org/x/text/transform"
)
