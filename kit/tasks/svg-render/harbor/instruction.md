# SVG renderer in Rust

`/app` holds a Rust crate, `svgrender`, meant to turn an SVG file into a PNG image. Right now it only parses its arguments. You write the renderer. Its output must match what resvg 0.48 (the Rust SVG renderer) produces for static SVG: document structure, basic shapes and paths, fill and stroke painting, markers, opacity and blending, gradients and patterns, clipping paths and masks, and filter effects. Text and raster images (`<image>`, `feImage`) are out of scope; none of the files you are scored on use them.

You get no crates and no network. The parser, the geometry, the stroker, the rasterizer, the compositor, the filter primitives and the PNG writer are all yours to write, using only the Rust standard library.

## Workspace

```
/app/Cargo.toml            the crate (edition 2024, no dependencies); you may add path-dependency crates of your own
/app/src/main.rs           the CLI entry point: argument parsing only
/app/samples/<area>/<feature>/<case>.svg   197 sample inputs
/app/samples/<area>/<feature>/<case>.png   their expected renderings at --width 300
/app/tools/selfcheck.py    builds the crate the way the grader does and scores it on the samples
/app/tools/imgcmp.py       the PNG decoder and the image comparison rule the grader uses
/app/.timer/               the time budget (see below)
```

`/app` is a git repository with one commit. The toolchain is Rust 1.98.0 (`cargo`, `rustc`, `rustfmt`, `clippy`) and Python 3.11 for the tools. The six areas under `samples/` are `structure`, `shapes`, `painting`, `paint-servers`, `masking` and `filters`; the feature folders inside them name what each case exercises (for example `painting/marker`, `paint-servers/radialGradient`, `filters/feTurbulence`). Each SVG is a small, single-purpose test with a 200 x 200 user space; many draw a red shape that a correct renderer covers completely, and most draw a thin black frame.

## What to deliver

A binary built from the crate with

```
cargo build --release --offline
```

and invoked as

```
target/release/svgrender --width 300 in.svg out.png
```

The contract:

- **Build.** The grader copies `/app` without `target/`, `.git/` and `.timer/`, then runs the command above in that copy as an unprivileged user (uid 65534), with an empty `CARGO_HOME` and no network. The build must finish within 30 minutes and must produce `target/release/svgrender`. Everything the build needs has to be inside `/app`.
- **Invocation.** Each render runs in its own scratch directory holding `in.svg`, as uid 65534, with `PATH=/usr/local/bin:/usr/bin:/bin` and `HOME` and `TMPDIR` set to that directory. A render gets 30 seconds and 4 GiB of address space. Four renders run at the same time.
- **Image size.** Take the SVG's size as resvg resolves it: `width` and `height` on the root `<svg>` default to `100%`; a percentage is taken of the `viewBox` size, or of 100 x 100 when there is no `viewBox`. Round each dimension to the nearest integer (at least 1). With `--width N`, the output is N pixels wide and `ceil(N * h / w)` pixels high, where `w` and `h` are the rounded size. Without `--width`, the output has the rounded size.
- **Placement.** The whole document is drawn with the transform `scale(W / sw, H / sh)`, where `W` x `H` is the output size and `sw` x `sh` is the unrounded SVG size, on a fully transparent canvas.
- **Output.** `out.png` is a non-interlaced PNG with straight (not premultiplied) alpha in sRGB. Any bit depth and colour type works (8-bit RGBA is the obvious choice). It must be a regular file the renderer itself wrote, under 64 MiB. Exit with status 0 after writing it.
- **Errors.** If the input cannot be rendered, exit non-zero and do not leave an `out.png` behind. A missing or unreadable file counts as a failed case.
- **Processes.** The renderer must not leave any process running after it exits. A leftover process of uid 65534 after the renders fails the anti-cheat gate.

Rendering conventions, where SVG leaves a choice or resvg made one:

- 96 dpi for absolute units (`in`, `cm`, `mm`, `pt`, `pc`). The default `font-size` is 12, so `1em` is 12 user units and `1ex` is half an em.
- The user language is `en`: `systemLanguage="en"` and `systemLanguage="en-US"` match, other languages do not.
- Shapes are anti-aliased one at a time with per-shape coverage, as Skia does; a shape underneath can show faintly through the anti-aliased edge of an identical shape on top. `shape-rendering="crispEdges"` and `optimizeSpeed` turn anti-aliasing off for that element.
- Group opacity, clip paths, masks, filters and blend modes are applied to an offscreen layer that is then composited.
- Filters work in device pixels: the filter region and each primitive subregion are transformed to the canvas and snapped outward to whole pixels, and lengths such as `stdDeviation`, `dx`/`dy` and `radius` are scaled by the current transform. `color-interpolation-filters` defaults to `linearRGB`. `feGaussianBlur` uses the three-box-blur approximation when a scaled deviation is at least 2 and a recursive (IIR) Gaussian below that; deviations under 0.05 count as 0.
- A pattern tile is rendered into its own image at device resolution, with its pixel size rounded to whole pixels, then painted as a repeating image with bicubic filtering.
- Where SVG 1.1 and SVG 2 disagree, or the specification leaves room, the expected images follow resvg 0.48. The samples show many of these choices.

## In scope

The cases come from resvg's own regression suite and cover:

- **structure**: `svg` (nested, `viewBox`, `preserveAspectRatio`, sizes), `g`, `defs`, `use` (including nested and recursive references), `symbol`, `switch` and `systemLanguage`, the `<style>` element (CSS selectors) and the `style` attribute, `transform` and `transform-origin`.
- **shapes**: `rect` (with the `rx`/`ry` rules), `circle`, `ellipse`, `line`, `polyline`, `polygon` and `path` (the full path grammar, including arcs, implicit commands and recovery from bad data).
- **painting**: colour syntax (`rgb()`, `hsl()`, named colours, `currentColor`, `transparent`), `fill`, `fill-rule`, `fill-opacity`, `stroke` and all `stroke-*` properties (joins including `miter-clip`, caps, miter limit, dashes, offsets), markers, `paint-order`, `context-fill` and `context-stroke`, `opacity`, `display`, `visibility`, `overflow`, `shape-rendering`, `isolation` and `mix-blend-mode`.
- **paint-servers**: `linearGradient`, `radialGradient` (with focal point), `stop`, `spreadMethod`, `gradientUnits`, `gradientTransform`, attribute inheritance through `href`, and `pattern` (units, content units, `viewBox`, `patternTransform`, nesting).
- **masking**: `clipPath` (units, transforms, clip paths on clip paths, `clip-rule`, which children count), `mask` (units, content units, `mask-type`, masks on masks).
- **filters**: the `filter` element (region, units, primitive subregions, `in`/`result` chaining, `href`), CSS filter functions (`blur()`, `drop-shadow()`, `grayscale()` and the rest), `feBlend`, `feColorMatrix`, `feComponentTransfer`, `feComposite`, `feConvolveMatrix`, `feDiffuseLighting` and `feSpecularLighting` with `feDistantLight`, `fePointLight` and `feSpotLight`, `feDropShadow`, `feFlood`, `feGaussianBlur`, `feMerge`, `feMorphology`, `feOffset`, `feTile` and `feTurbulence`.

Invalid values, broken references and reference cycles appear on purpose. Handle them the way resvg does (usually by ignoring the attribute or skipping the element) rather than failing the whole render.

## Building and checking your work

```
cd /app
cargo build --release --offline                        # your normal loop
python3 tools/selfcheck.py                             # clean build like the grader, then every sample
python3 tools/selfcheck.py --fast -k marker            # reuse target/, only samples whose path contains "marker"
python3 tools/selfcheck.py --fast --diff /tmp/diff     # expected | yours | off pixels, for failing cases
```

`selfcheck.py` reports the build result, a pass count per area and a score estimate on the samples. It applies the grader's comparison rule (`tools/imgcmp.py`) and the grader's leftover-process check, and when run as root it builds and renders as uid 65534 like the grader does. The samples are a small part of what is scored, so treat the sample score as an estimate.

## Scoring

The grader renders 822 SVG files that are not in `samples/`, from the same six areas in about the same proportions (structure 140, shapes 94, painting 211, paint-servers 106, masking 62, filters 209), each at `--width 300`. Their expected images were produced by resvg 0.48 with the conventions above.

A case passes when `out.png` exists, decodes, has exactly the expected size, and has at most `max(4, floor(0.0005 * W * H))` off pixels (45 for a 300 x 300 image). Both images are compared as premultiplied RGBA on a 0-255 scale. A pixel is off when some channel differs by more than 10 and neither allowance below explains it:

1. **Moved edge.** For every channel, your value lies within 10 of the range of the expected 3 x 3 neighbourhood, and the expected value lies within 10 of the range of your 3 x 3 neighbourhood.
2. **Different anti-aliasing.** The largest channel difference is at most 96, and both images have an edge there: the 3 x 3 neighbourhood spans at least 64 levels in some channel in both images.

`tools/imgcmp.py` is this rule in code.

```
reward = (cases passed) / 822
```

Hard gates, each scoring exactly 0:

- the build fails, times out or does not produce `target/release/svgrender`;
- a process of uid 65534 is still running after the renders finish.

A crash, a timeout, a non-zero exit, a missing or unreadable PNG or a wrong size fails that case only; the denominator stays 822. resvg 0.48 itself passes all 822 cases, so a renderer that matches it scores 1.0. The untouched crate renders nothing and scores 0.

## Time budget

You have 20 hours. The system clock does not tell you how much is left; `/app/.timer` does. Run `cat /app/.timer/remaining_secs` before any long build or full sample run. The files `alert_30min`, `alert_10min` and `alert_5min` appear in `/app/.timer/` as the budget runs down.

## Constraints

- Rust and the standard library only. No third-party crates are available: there is no registry and no network.
- The renderer reads its input file and writes `out.png`, nothing else. Do not shell out to other programs (no SVG converter is installed anyway).
- Do not rely on anything outside `/app` at build time: the grader builds a copy.
- Keep `cargo build --release --offline` working at every commit you leave behind.

## Operating rules

Nobody will answer questions, so make the call yourself and keep going. A renderer like this grows in layers: parse the document into a tree, resolve styles and references, flatten shapes into paths, stroke them, fill them with coverage anti-aliasing, then composite layers for opacity, clipping, masks and blending. Get a thin version of the whole pipeline through the simple cases first, then go deeper wherever the most samples fail. Every case is worth the same, so check the per-area numbers from `selfcheck.py` and the diff images before you pick the next fix.

Commit whenever the sample score goes up, and revert experiments that do not move it. Check `/app/.timer/remaining_secs` before large refactors, and stop starting new features when `alert_30min` appears: a clean build with slightly fewer features beats a broken one, because a failed build scores 0. The samples are only a slice of the scored cases. Fix behaviour rather than individual files, so the fix also holds on SVGs you have not seen.
