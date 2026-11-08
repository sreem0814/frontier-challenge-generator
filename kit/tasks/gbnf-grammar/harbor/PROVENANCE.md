# Provenance

## Source

llama.cpp, https://github.com/ggml-org/llama.cpp, commit `39da130fcd1b6ca47d3c0522a40eccff41ea3dfb` (2026-10-20, "ggml-cuda : support ssm_conv kernel size 7 (#30873)"), MIT licence. The graded subsystems are upstream's GBNF grammar engine (`src/llama-grammar.cpp`, 1,530 lines), its JSON schema document builder (`common/json-schema.cpp`, 514 lines) and its JSON-schema-to-GBNF converter (`common/json-schema-to-grammar.cpp`, 1,028 lines) at that commit. llama.cpp uses them to constrain token sampling to a grammar, for example to force valid JSON or tool calls.

## Extraction

The image downloads the source archive of that commit and, in the same layer, keeps only the build files, `ggml/`, `src/`, `include/`, `common/`, `vendor/`, `grammars/`, `licenses/`, `LICENSE` and five vocabulary-only model files, then replaces the three files above with stubs that keep every declared function. Removed with the rest of the tree: the upstream tests (which embed expected grammars and converter output), the examples (including the Python pydantic-to-grammar generator), the server and its web UI, the documentation and the Python packages. The image checks the result against a fixed hash and ships it without git history at `/app`, plus a pristine copy at `/usr/src/llama-base`.

The reference solution is the upstream text of the three files. The hidden set (2,800 cases) and the 326 visible samples come from seeded generators of random GBNF grammars, broken grammars, accepted strings found by walking the upstream engine, string mutations, token scripts over the five vocabularies and random JSON schemas. Every case was run three times through upstream's code with identical results; transcripts were frozen as hashes, and the converter's grammars as verdicts on generated JSON texts. Cases that the stubs already pass were dropped.

## Why it is real work

Grammar-constrained decoding is how inference servers guarantee structured output. Porting or re-implementing it, for a new runtime or a binding that cannot link llama.cpp, means matching a pushdown matcher, its token-level masking with partial UTF-8, lazy triggers and a schema converter whose output other components depend on, all against an existing implementation's exact behaviour.
