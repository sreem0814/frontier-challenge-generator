# Record-accessor paths in Fluent Bit's modify filter

`/app/fluent-bit` is Fluent Bit at upstream commit f4739648 (the 5.1 development line), a log processor written in C. Its `modify` filter (`plugins/filter_modify/`) edits each record with rules such as `Set`, `Rename` and `Copy`, gated by optional `Condition`s. Rules only understand top-level keys: `Set $kubernetes['labels']['team'] core` adds a key literally named `$kubernetes['labels']['team']`, `Remove $a['b']` does nothing, and conditions accept record-accessor keys but fail on array indexes. This is upstream issue #4651, open since 2022 with no implementation. Your job is to implement it completely: record-accessor *paths* in every rule and condition of the modify filter, with the exact behaviour specified below.

## Workspace

- `/app/fluent-bit/` – the source tree, a git repository with one commit (the starting point). `build/` is already configured and built with the options the grader uses.
- `/app/tools/build.sh` – configures (first run only) and builds the targets the grader builds: `fluent-bit-shared`, `fluent-bit-bin`, `flb-rt-filter_modify`, `flb-it-record_accessor`. An incremental rebuild after editing `modify.c` takes seconds.
- `/app/check/selfcheck.py` – runs the sample cases through your build; `/app/check/samples.jsonl` – 144 sample cases with expected results; `/app/check/harness/modify_harness.c` – the exact program the grader uses to drive the filter.
- There is no network. gcc, cmake, flex, bison, gdb and python3 are installed.

## What is graded

The grader unpacks a pristine copy of the starting tree and copies over only these paths from `/app/fluent-bit` (regular files; symlinks fail the run):

- `plugins/filter_modify/` (the whole directory, including its CMakeLists.txt)
- `src/record_accessor/` and `include/fluent-bit/record_accessor/`
- `src/flb_record_accessor.c`, `src/flb_ra_key.c`, `src/flb_mp.c`, `include/fluent-bit/flb_record_accessor.h`, `include/fluent-bit/flb_ra_key.h`, `include/fluent-bit/flb_mp.h`

Changes anywhere else are ignored. A delivered file that mentions `/tests/`, `/logs/verifier`, `hidden.jsonl` or `/opt/fluent-bit-base` fails the run. The tree is configured with

    cmake -DFLB_TESTS_RUNTIME=On -DFLB_TESTS_INTERNAL=On -DFLB_USE_SIMDUTF=No -DFLB_WASM=No -DFLB_LUAJIT=No \
          -DFLB_KAFKA=No -DFLB_EXAMPLES=No -DFLB_BACKTRACE=No -DCMAKE_EXPORT_COMPILE_COMMANDS=On

and built (`fluent-bit-shared`, `flb-rt-filter_modify`, `flb-it-record_accessor`) as an unprivileged user. The upstream test programs are the starting tree's own `tests/runtime/filter_modify.c` and `tests/internal/record_accessor.c`, so keep their behaviour.

Each case is a filter configuration plus a few records. `modify_harness.c` (linked against `libfluent-bit.so`) creates a `modify` filter instance with `flb_filter_new`, sets `match *` and the case's properties in order with `flb_filter_set_property`, calls `flb_filter_init`, then passes all records as one chunk to the plugin's `cb_filter` callback and decodes the bodies that come back (on `FLB_FILTER_NOTOUCH` the input chunk counts as the output). A case passes when the configuration is refused exactly when it should be (`flb_filter_init` fails, or the instance has no context), and otherwise every output body equals the expected body exactly: the same map entries in the same order, duplicates included, the same array elements, the same msgpack types. A crash, a hang (180 s per batch of cases) or a wrong record count fails the case.

## Paths

A rule or condition argument that starts with `$` is a *path*. A path is `$` plus a root name, followed by zero or more subscripts, with no spaces:

- root name: a letter or `_`, then letters, digits, `_`, `-` or `/`. A root starting with `TAG` is reserved (it is the record accessor's tag syntax), and roots beginning with a digit are regex-capture references; neither is a path.
- subscript: `['name']` (a map key; the name may contain any character except a space, tab, comma or double quote, and a single quote is written `''`) or `[N]` (an array index, decimal, no sign, no leading zero).

`$kubernetes['labels']['app.kubernetes.io/name']`, `$items[0]['id']`, `$a['it''s']` and `$svc/name` are paths. `$`, `$a[`, `$a['b'`, `$a[x]`, `$a[-1]`, `$a[01]`, `$a.b`, `$a['b']x`, `$TAG`, `$TAG[0]`, `$1` and `$['a']` are not: wherever an argument starts with `$` but is not a valid path, the filter must refuse the configuration (`cb_init` fails).

**Resolving** a path walks from the record body: a name step needs the current value to be a map and selects the **last** entry whose key is a string equal to the name; an index step needs an array with more than N elements. The path *resolves* when every step succeeds; it then addresses one slot (a map entry or an array element). A step into anything else (a scalar, a map for an index, an array for a name, a missing key, an index out of range) means the path does not resolve.

**Writing** a value at a path (used by `Set`, `Add`, and the destination forms of `Rename` and `Copy`): if the path resolves, the slot's value is replaced in place (a map entry keeps its key and position). Otherwise the walk proceeds as far as it resolves; at the first missing key, the rest of the path must consist of name steps only, and each missing level is created as a new map entry appended at the end of its parent map (`{name: {next: ... {last: value}}}`). If the walk fails for any other reason (an index step that does not resolve, a name step into a non-map), nothing is written and the rule does not apply.

## Rules with a path

Arguments are split on spaces as before (a double-quoted argument may contain spaces), and property names are case-insensitive. Rules are applied in configuration order; each sees the result of the previous one. A rule that does not apply leaves the record unchanged. Values given in a rule are always stored as msgpack strings.

- `Set PATH VALUE` – write VALUE at PATH.
- `Add PATH VALUE` (and its deprecated alias `Add_if_not_present`) – if PATH does not resolve, write VALUE at PATH; otherwise nothing.
- `Remove PATH` – if PATH resolves, delete the slot: the map entry, or the array element (later elements move down).
- `Rename PATH NAME`, `Hard_rename PATH NAME` (NAME does not start with `$`) – PATH must end with a name step, otherwise the configuration is refused. If PATH resolves, the addressed entry gets the key NAME in place. `Rename` does not apply when another entry of the same map already has the key NAME; `Hard_rename` first deletes every other entry of that map whose key is NAME. If NAME equals the current key, nothing changes.
- `Copy PATH NAME`, `Hard_copy PATH NAME` – PATH must end with a name step, otherwise the configuration is refused. If PATH resolves, a new entry NAME holding a copy of the value is inserted directly after the addressed entry. `Copy` does not apply when another entry of that map already has the key NAME; `Hard_copy` first deletes every other entry whose key is NAME. If NAME equals the current key, nothing changes.
- `Rename SRC DST`, `Hard_rename SRC DST` (DST is a path) – a move. SRC must resolve. `Rename` does not apply when DST resolves. Then SRC is deleted (as `Remove`), and the moved value (any type, unchanged) is written at DST in the resulting record; if that write fails, the rule does not apply at all. If DST is the same path as SRC, nothing changes.
- `Copy SRC DST`, `Hard_copy SRC DST` – SRC must resolve; a copy of its value is written at DST. `Copy` does not apply when DST resolves. Same path, nothing changes.
- `Remove_wildcard PATH PREFIX`, `Remove_regex PATH REGEX`, `Move_to_start PATH PREFIX`, `Move_to_end PATH PREFIX` – the two-argument form works on the keys of the map at PATH (if PATH does not resolve to a map, nothing happens). `Remove_wildcard` deletes the entries whose key starts with PREFIX (a plain byte prefix, as in the existing one-argument form), `Remove_regex` those whose key matches REGEX; `Move_to_start` puts the matching entries first and `Move_to_end` last, each group keeping its order. In this form the first argument must be a path, otherwise the configuration is refused. The one-argument forms are unchanged.

Paths are never compiled as regular expressions (the existing code compiles every rule argument as a regex and refuses those that are not; for a rule whose first argument is a path only the REGEX of `Remove_regex` is compiled). An invalid REGEX refuses the configuration. A rule with more arguments than its form takes is refused.

## Conditions with a path

All conditions are evaluated on the record as it arrives; the rules run only when every condition holds.

- `Key_exists PATH` / `Key_does_not_exist PATH` – PATH resolves / does not resolve (whatever the value's type, null included).
- `Key_value_equals PATH VALUE` – PATH resolves to a string (or binary) whose bytes equal VALUE. `Key_value_matches PATH REGEX` – PATH resolves to a string, or a boolean read as `true`/`false`, matching REGEX. `Key_value_does_not_equal` and `Key_value_does_not_match` hold when PATH resolves and the positive form does not; both are false when PATH does not resolve.
- `A_key_matches PATH REGEX` – PATH resolves to a map with at least one key matching REGEX; `No_key_matches PATH REGEX` is its negation. With a single argument these remain the existing top-level forms.
- `Matching_keys_have_matching_values PATH KEY_REGEX VALUE_REGEX` – PATH resolves to a map, and every entry whose key matches KEY_REGEX has a value matching VALUE_REGEX (string, or boolean as `true`/`false`); true when no key matches. `Matching_keys_do_not_have_matching_values` with a path is its negation. With two arguments these remain the existing top-level forms; a path form with any other number of arguments is refused.

An argument position that takes a path refuses the configuration when it starts with `$` but is not a valid path. Regular expressions are Onigmo searches (unanchored unless you write `^`/`$`), as everywhere in the filter.

## Plain keys stay as they are

Rules and conditions whose first argument does not start with `$` keep the starting tree's behaviour exactly (for example `Set a 1` still removes every `a` and appends one at the end, `Rename a b` renames every `a`, and the second argument of a plain `Rename`/`Copy` is a key name even if it starts with `$`). A path always addresses one slot, so `Set $a 1` replaces the last `a` in place. A separate set of plain-key cases checks this.

## Scoring

Hard gates, each scoring 0: a delivered symlink or forbidden reference, a failed configure or build, a harness that does not compile against your headers, or any failing test in the two upstream programs (`flb-rt-filter_modify`, `flb-it-record_accessor`).

The graded cases are fixed: 3,200 path cases in nine groups and 400 plain-key cases, generated the same way as the samples but different from them. Every path case fails on the starting tree; every plain-key case passes on it.

    reward = legacy * ( 0.14 set_add + 0.06 remove + 0.13 rename + 0.13 copy + 0.13 keysets
                      + 0.09 conditions + 0.10 cond_keysets + 0.06 config + 0.16 chains )

Each group term is the fraction of that group's cases passed; `legacy` is the fraction of plain-key cases passed. `rename` and `copy` mix name and destination forms, `keysets` are the two-argument key-set rules, `cond_keysets` the path forms of the key-matching conditions, `config` refused and accepted configurations, and `chains` three to six rules (with conditions half the time) on four records. A case that crashes or times out fails; the denominators never change. The untouched tree scores exactly 0.

## Checking your work

    bash /app/tools/build.sh                         # build (incremental)
    python3 /app/check/selfcheck.py --upstream        # samples per group, the formula on them, upstream suites
    python3 /app/check/selfcheck.py --bucket rename --show 3

Each line of `samples.jsonl` has `id`, `bucket`, `props` (property name and value pairs, in order), `records` (hex-encoded msgpack bodies), `status` (`ok` or `init_fail`) and `outputs` (expected hex bodies, or null when the configuration must be refused); the graded cases use the same format. The self-check prints records as JSON with maps written `{"__map__": [[key, value], ...]}` to keep order and duplicates. You can also run `build/bin/fluent-bit -i dummy -p 'dummy={"a":{"b":[1,2]}}' -p samples=1 -F modify -p 'Match=*' -p "Set=\$a['c'] x" -o stdout -m '*'`.

## Time

You have 8 hours. `cat /app/.timer/remaining_secs` shows the seconds left; `alert_30min` and `alert_10min` appear in `/app/.timer/` as the end nears. The system clock tells you nothing about the budget.

## How to work

No one will answer questions; decide and keep going. Keep the tree building at every point: a broken build scores 0, a partial feature scores its share. The samples are a small slice of the graded cases, so implement the specification, not the samples. Check the timer before long builds, commit often, and leave time for a final `build.sh` plus `selfcheck.py --upstream`.
