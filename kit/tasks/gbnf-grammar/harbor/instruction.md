# Rebuild the llama.cpp grammar engine and JSON-schema converter

`/app` is llama.cpp at commit `39da130` (October 2026), trimmed to the library, the `common` utilities, the vendored headers, the example grammars and five vocabulary files. Three implementation files were replaced by stubs that compile but do nothing useful:

| File | What it implemented |
| --- | --- |
| `src/llama-grammar.cpp` | the GBNF grammar engine: parser and printer, pushdown stacks, character and token matching, token-level masking of a candidate list, lazy grammars with trigger tokens and trigger patterns, clone and free |
| `common/json-schema.cpp` | `common_chat_schema_from_json()`: a JSON schema turned into the typed document of `common/json-schema.h`, plus `value_types()`, `may_be_string()`, `kind_name()` and `type_name()` |
| `common/json-schema-to-grammar.cpp` | `json_schema_to_grammar()`, `build_grammar()` and `gbnf_format_literal()`: JSON schema to GBNF text |

Your job is to write those three files again so that the library behaves exactly like upstream llama.cpp at that commit. Nothing else in the tree is graded, and nothing else may need to change.

## Workspace

- `/app/src/llama-grammar.h`, `/app/common/json-schema.h`, `/app/common/json-schema-to-grammar.h`: the interfaces. They are fixed; the grader compiles your files against its own pristine copies, so editing a header has no effect except to break your build.
- `/app/src`, `/app/common`, `/app/include`, `/app/ggml`, `/app/vendor`: the rest of llama.cpp. Callers of your code live here (`src/llama-sampler.cpp`, `common/sampling.cpp`, `common/chat.cpp`, `common/peg-parser.cpp`) and show how it is used.
- `/app/grammars/README.md`: upstream's GBNF guide (syntax, repetition, tokens, comments, the JSON schema section). Its JSON-schema output examples come from an older converter; where they disagree with the sample cases, the samples are right. `/app/grammars/*.gbnf` are real grammars.
- `/app/models/ggml-vocab-{llama-spm,llama-bpe,phi-3,deepseek-coder,falcon}.gguf`: vocabulary-only model files used by the token cases.
- `/app/build.sh`: configures (once) and builds `libllama`, `llama-common` and `check/case_runner` into `/app/build` with the options the grader uses (CMake, Ninja, Release, static libraries, `GGML_NATIVE=OFF`). Incremental after the first run.
- `/app/check/case_runner.cpp`: the program the grader runs. Read it: it defines every case kind and prints each transcript.
- `/app/check/selfcheck.py` and `/app/check/samples/`: 326 sample cases with their expected transcripts, and the self-check that scores them.
- `/usr/src/llama-base`: a read-only pristine copy of the starting tree. The grader verifies it file by file; do not touch it.
- The toolchain is Debian 12's gcc 12, CMake 3.25 and Ninja; Python 3.11 is there for the self-check. There is no network.

## What the grader does

1. It copies `/usr/src/llama-base`, replaces the three stubs with your `src/llama-grammar.cpp`, `common/json-schema.cpp` and `common/json-schema-to-grammar.cpp` from `/app` (each must be a regular file under 4 MiB; a missing one keeps the stub), and builds `case_runner` with its own copy of `check/CMakeLists.txt` and `check/case_runner.cpp`, as an unprivileged user, with up to 40 minutes for the build.
2. It runs about 2,800 hidden cases through `case_runner`, one forked process per case with a 10 second limit and a 4 GiB address-space limit. A crash, a timeout or a missing transcript fails the case.
3. It compares each transcript with the one upstream llama.cpp produces, as described per bucket below, and computes the reward.

The hidden cases are generated the same way as the samples, from different random seeds: random GBNF grammars (valid and broken), strings that grammars accept, mutations of those strings, scripted token streams over the five vocabularies, and random JSON schemas (valid and invalid) with JSON texts derived from them.

## Buckets

| Bucket | Weight | Case kind | What must match |
| --- | --- | --- | --- |
| `gbnf_parse` | 0.09 | `P` | for one to four grammar texts: the `parse()` result, every symbol id and name, every rule's element list, the `print()` output, and whether `llama_grammar_init_impl` succeeds |
| `gbnf_match` | 0.11 | `M` | for one grammar and up to 16 strings: ACCEPT, PREFIX or REJECT at the first failing code point, fed one code point at a time through `llama_grammar_accept` |
| `gbnf_stacks` | 0.06 | `S` | the set of stacks (as rule index and element offset, sorted) after init and after every code point of one string |
| `gbnf_tokens` | 0.12 | `T` | with a vocabulary loaded: the tokens `llama_grammar_apply_impl` leaves allowed over the full vocabulary, the result of `llama_grammar_accept_impl` per token (state: awaiting trigger, stack count, whether a stack is complete, partial UTF-8 state, trigger buffer), exceptions, clones, lazy grammars with trigger tokens and patterns |
| `schema_doc` | 0.12 | `D` | for one to four schemas: the document `common_chat_schema_from_json` builds (every node's kind and fields, `value_types()` and `may_be_string()` per node, the `refs` map and each ref's target), or that it throws |
| `schema_text` | 0.24 | `X` | the exact text of `json_schema_to_grammar(schema, true)` or that it throws, `gbnf_format_literal` results, and `build_grammar` scripts (`add_rule` and `add_schema` return values and the final text, with and without `dotall`) |
| `schema_lang` | 0.26 | `L` | the language of the grammar your converter produces for one schema: the grader parses your grammar text with the original grammar engine and checks it against hidden strings (valid JSON texts, near misses and truncations); the case passes when every string gets the same verdict (ACCEPT, PREFIX or REJECT) as with upstream's grammar; a converter that throws fails the case (every `schema_lang` schema converts upstream) |

For every bucket except `schema_lang` a case passes only when the transcript is byte-identical to upstream's. `schema_lang` does not compare text: any grammar with the same accepted language and prefixes passes, so it rewards a converter that is right about JSON even where its rule names or layout differ.

## Reward

```
reward = sum over buckets b of  weight_b * passed_b / total_b
```

with the weights above (they sum to 1). The denominators are fixed by the hidden set. The upstream implementation passes every case and scores exactly 1.0; the stubs score exactly 0.

Hard gates, each of which sets the reward to 0:

- the library or `case_runner` does not build from the pristine tree plus your three files;
- `/usr/src/llama-base` differs from its original contents;
- system files the grader relies on were modified (the Python interpreter and libraries, the compiler and binutils, libc, `/etc/ld.so.preload`, `/etc/ld.so.conf.d`).

Self-check for the build gate: `./build.sh` (it builds the same targets with the same options). Self-check for the score: `python3 check/selfcheck.py` prints each bucket's sample pass count and the weighted estimate; `--fails 20` lists failing ids and `--case ID` prints the expected and the actual transcript. One difference: the self-check judges `schema_lang` grammars with your own engine, the grader with the original one.

## Behaviour notes

These are the points where a reasonable reimplementation most often differs from upstream. The samples are the final word.

- Parser: symbol ids are assigned in order of first appearance, including references to rules defined later. Groups, `?`, `*`, `+` and `{m,n}` are rewritten into generated rules named `<rule>_<id>`; the shape of that rewrite is visible in the sample `print()` output. A parse error clears the rules and returns false. `llama_grammar_init_impl` returns null for parse errors, a missing root symbol, undefined rules and left recursion (including through rules that can match the empty string).
- Stacks hold pointers into the grammar's own rules and always end at a terminal element or are empty; an empty stack means the input so far is a complete match. Duplicate stacks are not kept.
- Token masking: end-of-generation tokens are allowed only when some stack is complete; a token whose text is empty or starts with a NUL byte is rejected; bytes of an incomplete UTF-8 sequence carry over to the next token. `<[id]>` and `!<[id]>` match token ids; `<text>` is resolved through the vocabulary and must be exactly one token.
- Lazy grammars buffer text until a trigger token or a trigger pattern fires, then replay the buffered tokens from the trigger onwards. A pattern anchored with `^` and `$` must match the whole buffer; others may match anywhere; the replay starts at the first non-empty capture group, or at the match when there is none.
- `llama_grammar_accept_impl` and `llama_grammar_accept_str` throw `std::runtime_error` when no stack survives a piece.
- `json-schema.h` documents the document model. The precedence of keywords (`$ref`, `oneOf`/`anyOf`, `type`, `const`, `enum`, then structural keywords), the folding of exclusive bounds and the rounding of fractional bounds are observable in the `schema_doc` samples.
- `json_schema_to_grammar` throws `std::invalid_argument` for schemas it cannot convert; patterns that are valid regular expressions without a grammar equivalent become an unconstrained string instead.

## Constraints

- Write C++17 that builds with the shipped toolchain and the libraries already linked (the standard library, `common/json.h` over the vendored nlohmann JSON, and what `src/` and `common/` provide). New source files are not picked up: everything goes into the three files.
- The upstream implementation is not on this machine and there is no network. Work from the headers, the callers, the GBNF guide, the samples and the case runner.
- The grader's copy of the case runner is used, not yours; changes you make under `/app/check` only affect your own self-check.

## Time

You have 8 hours. The budget timer lives in `/app/.timer`: `cat /app/.timer/remaining_secs` before long builds or test runs; `alert_30min` and `alert_10min` appear there as the end nears. The container clock does not tell you how much budget is left.

## How to work

Nobody will answer questions, so make the call yourself and keep going. A full build takes a few minutes the first time and seconds after an edit to one of your files, so iterate in small steps and rerun the self-check often. Keep all three files compiling at every point: a broken build scores nothing, and every case you pass counts. The schema buckets carry most of the weight; the converter and the document builder are worth starting early rather than polishing the engine forever. When a change does not move the sample counts, revert it and take the next gap. The hidden set is eight times the samples and drawn from the same generators, so fix the general rule behind a failing sample rather than the sample. Leave the last 20 minutes for a clean `./build.sh clean && ./build.sh` and a final self-check.
