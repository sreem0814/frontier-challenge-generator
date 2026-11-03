# Provenance

## Source
FreeRDP 3.32.2, the release tarball `freerdp-3.32.2.tar.gz` published on the project's GitHub release page
(SHA-256 e95a505c0057e4d06a3b120477c421028769deba4db9c639ef3465d050f0955c; the tag points at commit
97eff6ddfbbfaa8e42a126d362686bd001ff8bdc), Apache License 2.0. The stream formats are the public
Microsoft protocol documents FreeRDP implements: [MS-RDPBCGR] (interleaved RLE), [MS-RDPEGDI] (planar),
[MS-RDPNSC] (NSCodec), [MS-RDPRFX] (RemoteFX) and [MS-RDPEGFX] (ClearCodec, progressive, ZGFX).

## Extraction
The image downloads the tarball, checks its hash and replaces 19 files of `libfreerdp/codec` with stubs
that keep every declared function but report failure: `interleaved.c`, `include/bitmap.h`, `bitmap.c`,
`planar.c`, `nsc.c`, `nsc_encode.c`, `clear.c`, `rfx.c`, `rfx_decode.c`, `rfx_dwt.c`, `rfx_quantization.c`,
`rfx_rlgr.c`, `rfx_encode.c`, `progressive.c`, `zgfx.c` and the SSE/NEON variants. Encoders went too,
because they spell out the inverse of each decoder. Everything else (winpr, primitives, colour
conversion, regions, the public headers) is untouched. `docs/bitmap-codecs.txt` describes the formats and
FreeRDP's behaviour in our own words. The reference solution is the original 3.32.2 source of the
removed files. The test streams come from our own Python encoders (RLE orders, planar and NSCodec RLE,
RemoteFX messages built from a port of the forward wavelet and the RLGR encoder, progressive first and
upgrade passes, ClearCodec layers and caches, ZGFX tokens); the pristine 3.32.2 library, built with the
grading options, decoded each one, and its status and output were frozen. Streams on which upstream
logged a warning, and truncated streams it accepts, were dropped.

## Why it is real work
This is the decoding layer every FreeRDP client relies on to show a remote desktop. Restoring it means
implementing a family of interacting codecs from their specifications until the output matches a
reference implementation bit for bit, with the stateful parts (RemoteFX frame state, progressive tile
upgrades, ClearCodec caches, the ZGFX history) and the bounds checks that untrusted server data requires.
