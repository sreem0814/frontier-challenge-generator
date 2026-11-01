# Provenance

## Source

The system is `github.com/gotd/td`, an MIT-licensed Go client for Telegram's MTProto protocol, at release v0.162.0 (commit be24580163e18c2b4d3557ffa03e250ec6a30335). The image fetches it as the module zip from the Go module proxy, checked against its go.sum hash (`h1:3pUzBsEbb0I5QquvfSkXihkVBXI+QTtdd/upijjUbkw=`). The behaviour follows Telegram's published MTProto documents: mtproto-transports (framing and obfuscation), description and description_v1 (message keys), auth_key (key exchange) and api/pfs (temporary key binding).

## Extraction

`/app` is that tree with the `_fuzz` corpora dropped and the copy in the module cache deleted. All `.go` files directly in `proto/codec`, `mtproxy/obfuscated2`, `crypto`, `exchange`, `mtproto`, `mtproto/salts` and `rpc`, tests included, were replaced by stubs that keep every exported declaration and its doc comment but return errors or zero values. The doc comments were extended with the byte-level contract the callers rely on. `selfcheck/` (an API check, 76 sample vectors, a runner script) was added. Nothing else changed; the callers and their tests are upstream.

The reference solution is the upstream implementation of those seven packages at the same commit, under `solution/ref/`, unchanged except that three upstream to-do comments were reworded. The grader builds a clean tree from a snapshot of the starting state plus the agent's files. It runs 596 behavioural cases generated from fixed seeds against a sealed copy of the same upstream code, which acts as the peer and the decoder, plus a scripted MTProto server built from that copy for the session cases, and freezes the reference outputs. It also runs 34 upstream tests from the dependent packages that fail on the stubs and pass on the reference on repeated runs.

## Why it is real work

This is the layer any MTProto client or server has to get right: framing that must match other implementations byte for byte, AES-IGE message encryption with its key derivation, RSA_PAD and the Diffie-Hellman checks of the key exchange, both sides of that exchange with every security check in the right place, and the session on top: msg_id and seq_no discipline, acknowledgements, salts, retries and temporary key binding. Anyone porting a client to a new language, auditing one, or building a test server writes exactly this code against the same documents.
