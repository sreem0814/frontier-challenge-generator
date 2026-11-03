# Restore FreeRDP's codec decoders

`/app` is the FreeRDP 3.32.2 source tree with the implementations of seven codecs removed from
`libfreerdp/codec`: interleaved RLE, planar, NSCodec, ClearCodec, RemoteFX (RLGR entropy coding,
quantization, the 5/3 wavelet), RemoteFX progressive, and the RDP8 bulk compressor ZGFX. Every function
those files used to define is still there, but each one now reports failure. Your job is to write the
decoders back so that the library decodes RDP streams exactly as FreeRDP 3.32.2 does: same success or
failure, same bytes in the destination buffer. The upstream source is not available in the image and
there is no network.

## Workspace

```
/app/                              FreeRDP 3.32.2 (git repository, one commit: the starting state)
/app/libfreerdp/codec/             the codec module; the files you rewrite are listed below
/app/include/freerdp/codec/*.h     the public API of each codec (unchanged, the contract)
/app/docs/bitmap-codecs.txt        format and behaviour reference for the seven codecs: stream layouts,
                                   arithmetic, FreeRDP's checks, how the graded calls are made
/app/build.sh                      configures and builds libwinpr3 and libfreerdp3 into /app/build
/app/check/selfcheck.py            builds, runs the sample streams, prints a score estimate
/app/check/codec_runner.c          the program that calls the decoders (the grader uses the same code)
/app/check/samples/                417 sample sequences (cases.bin), expected results (expected.json) and
                                   the expected output buffers (expected.pack.xz)
/usr/src/freerdp-3.32.2/           the pristine starting tree; the grader builds from it (do not change it)
```

The rest of the tree works and may be used: winpr (streams, bit streams, pools, thread pools), the colour
conversion helpers in `libfreerdp/codec/color.c`, the region code in `region.c`, and the primitives in
`libfreerdp/primitives` (`primitives_get()`; the build uses the generic C versions). The original decoders
used them; `docs/bitmap-codecs.txt` names the calls whose exact results matter.

## What to deliver

Implement the decoders in these files under `/app/libfreerdp/codec/`:

```
interleaved.c  include/bitmap.h   interleaved RLE (bitmap updates)
planar.c                          planar
nsc.c                             NSCodec
clear.c                           ClearCodec
rfx.c rfx_decode.c rfx_rlgr.c     RemoteFX: message parsing, tile decode, RLGR1/RLGR3,
rfx_quantization.c rfx_dwt.c      dequantization, inverse DWT
progressive.c                     RemoteFX progressive
zgfx.c                            ZGFX
```

You may also edit `bitmap.c`, `nsc_encode.c`, `rfx_encode.c`, the private headers (`nsc_types.h`,
`nsc_encode.h`, `rfx_*.h`, `progressive.h`) and `sse/`, `neon/`, and you may add new `.c`, `.h` or `.inc`
files directly in `libfreerdp/codec/` (or its `include/`, `sse/`, `neon/` subdirectories). The build file
list is fixed, so a new `.c` file is only compiled if one of the listed files `#include`s it. A file over 4 MB, or more than 32 MB in total, is ignored. Nothing
outside those paths is used by the grader: every other file, including the public headers,
`CMakeLists.txt`, `color.c` and `region.c`, comes from the pristine copy.

The grader calls these entry points, with the arguments described per codec in `docs/bitmap-codecs.txt`
(and exactly as `check/codec_runner.c` does):

- `bitmap_interleaved_context_new`, `interleaved_decompress`, `bitmap_interleaved_context_free`
- `freerdp_bitmap_planar_context_new`, `freerdp_bitmap_decompress_planar`, `freerdp_bitmap_planar_context_free`
- `nsc_context_new`, `nsc_process_message`, `nsc_context_free`
- `clear_context_new`, `clear_decompress`, `clear_context_free` (subcodec 1 of ClearCodec is NSCodec)
- `rfx_context_new`, `rfx_context_set_pixel_format`, `rfx_context_reset`, `rfx_process_message`, `rfx_context_free`
- `progressive_context_new`, `progressive_create_surface_context`, `progressive_decompress`, `progressive_context_free`
- `zgfx_context_new`, `zgfx_decompress`, `zgfx_context_free`

Encoders (`interleaved_compress`, `freerdp_bitmap_compress_planar`, `nsc_compose_message`,
`rfx_encode_message`, `progressive_compress`, `zgfx_compress` and friends) and the `rfx_message_get_*`
accessors are not graded; leaving them as failing stubs is fine.

A test case is one decode call. Calls come in sequences: one context, one destination buffer, several calls
in order, so state carried by a context (RemoteFX header blocks and frame state, progressive tiles and
their upgrade passes, ClearCodec caches and sequence numbers, the ZGFX history) matters. Before the first
call the destination is filled with a fixed byte pattern in which every 32-bit pixel has alpha 0xFF. After
each call the grader checks:

- valid stream: the call reports success and the whole destination buffer, stride padding included, is
  byte-identical to FreeRDP 3.32.2's (for ZGFX: the returned bytes are identical);
- truncated stream (a valid first message of a sequence cut short so that a length field or an order runs
  past the end of the data): the call reports failure. A truncated case only counts when the decoder also
  passes the untruncated message, so failing everything earns nothing. There are no truncated cases for
  progressive, whose upstream status on malformed input is not graded.

Every sequence runs in its own process with a 20-second limit; a crash or a timeout fails the rest of that
sequence. Decoders must not read outside the buffers they are given.

## Building and checking your work

```
cd /app && ./build.sh                  # first run configures (about 20 s), later runs rebuild what changed
python3 /app/check/selfcheck.py        # build, run every sample, per-codec results and a score estimate
python3 /app/check/selfcheck.py --codec rfx --diff     # one codec, first differing pixel of each failure
python3 /app/check/selfcheck.py --seq 412 -v           # one sequence with its parameters and tags
python3 /app/check/selfcheck.py --dump /tmp/d         # raw got/expected buffers of failing steps
```

`build.sh` uses exactly the configure options of the grader (Release, shared libraries, `WITH_SIMD=OFF`,
client, server and channels off). The samples come from the same generators as the hidden cases, with
different seeds, and the self-check scores them with the grader's formula, so its estimate is a good guide.
The sample tags name the features a case uses (bits per pixel, RLE orders, colour loss level, subsampling,
RLGR mode, tile kinds, layers, segment kinds). `docs/bitmap-codecs.txt` is the reference for every stream
format; read the section of a codec before writing it.

## Scoring

The grader copies the files listed above from `/app/libfreerdp/codec` into a fresh copy of
`/usr/src/freerdp-3.32.2`, configures and builds `libwinpr3` and `libfreerdp3` with the options of
`build.sh` as an unprivileged user, compiles its runner against the result and runs 2,155 hidden sequences
(3,747 calls). With `passed_c / total_c` the fraction of calls passed in codec bucket `c`:

```
reward = 0.12 * interleaved + 0.12 * planar + 0.08 * nsc + 0.13 * clear
       + 0.18 * rfx + 0.27 * progressive + 0.10 * zgfx
```

FreeRDP's own decoders score exactly 1.0. Hard gates, each scoring exactly 0:

- the library does not build, or the runner does not link against it (check: `./build.sh` succeeds and
  `selfcheck.py` runs);
- anything under `/usr/src/freerdp-3.32.2` was changed, added or removed. Root can write there, but the grader checks every file against a manifest, so any change scores 0;
- the system Python or the tools the grader uses were modified, or `/etc/ld.so.preload` exists.

The denominator is fixed: a call that crashes, hangs or is never reached counts as failed.

## Time budget

You have 8 hours. The system clock does not tell you how much is left; `cat /app/.timer/remaining_secs`
does, and `/app/.timer/alert_30min` and `/app/.timer/alert_10min` appear as the budget runs down. Check it
before long builds and leave time for a last full self-check.

## Constraints

- C only, in the files above; no network; leave `/usr/src/freerdp-3.32.2` alone.
- Results must not depend on the CPU, the thread count or the order of the sequences.
- Do not special-case the sample streams; the hidden streams are different.

## How to work

No one will answer questions, so make the calls yourself and keep going. Codecs are independent buckets,
so a codec that works earns its share even if another one is unfinished: get each one decoding valid
streams first, then match the edge cases and the failure rules. Rebuild and rerun the self-check after
every meaningful change and keep the tree building at all times; a tree that does not build scores 0.
When a codec stalls, move to the next one and come back. Before the last half hour, run the full
self-check one more time and make sure `./build.sh` passes from a clean `build/` directory
(`./build.sh clean`).
