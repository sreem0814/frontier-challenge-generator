# Rebuild the MTProto transport, crypto and session layers of gotd/td

`/app` holds `github.com/gotd/td` at release v0.162.0, a Go client for Telegram's MTProto protocol. Seven of its packages have been cut back to their exported API: every function and method is still declared, with its doc comment, but returns an error or a zero value. Those packages carry the wire framing, the transport obfuscation, the message encryption, the authorization-key exchange and the encrypted session with its RPC engine, so nothing above them can talk to a server any more. Rebuild them. The rest of the module (`transport`, `telegram`, `tgtest`, `session`, `crypto/srp`) is unchanged and must work on top of your code, and your code must interoperate byte for byte with an independent MTProto implementation.

## Workspace

- `/app` is the module root (`go.mod`: `github.com/gotd/td`). You work as the unprivileged user `agent`, which owns `/app`. Go 1.25.14 is at `/usr/local/go`. Every dependency is already in `/go/pkg/mod` (read-only to you); there is no network (`GOPROXY=off`).
- The seven packages to rebuild:
  - `/app/proto/codec`: transport framing (abridged, intermediate, padded intermediate, full).
  - `/app/mtproxy/obfuscated2`: the obfuscated transport (AES-256-CTR with a 64-byte init header).
  - `/app/crypto` (the `.go` files directly in that directory; `crypto/srp` is intact): MTProto 2.0 and 1.0 message crypto, the RSA and Diffie-Hellman primitives of the key exchange, the temporary-key binding message.
  - `/app/exchange`: the client and server flows that create an authorization key.
  - `/app/mtproto` (directly in that directory) and `/app/mtproto/salts`: the client session (`Conn`): connecting, PFS key binding, encryption of every message, msg_id and seq_no discipline, acknowledgements, service messages, salts, pings.
  - `/app/rpc`: the request engine under `Conn.Invoke` (resend until acknowledged, results, errors, drops).
- The doc comment on each declaration states its contract. Where this file and a doc comment overlap, they agree; the doc comments carry the byte-level detail.
- Callers you must not break: `transport` (connections, listeners, codec detection), `telegram` (the client, built on `mtproto`), `tgtest` (an in-process server built on `exchange` and `crypto`), `session/tdesktop` (reads Telegram Desktop storage with `crypto.OldKeys`), `crypto/srp`, `cmd/mtprint`, `cmd/rsagen`. Their tests exercise your code end to end.
- `/app/selfcheck`: `api.go` (a compile-time check of every exported name and signature of the seven packages), sample vectors, and `run.sh` (see below).
- `/app` is a git repository with one commit, the starting state. `git diff` shows your work.
- The protocol documents (core.telegram.org/mtproto, /mtproto/auth_key, /mtproto/mtproto-transports, /mtproto/description, /api/pfs) are not reachable from here. Everything the grader relies on is in the doc comments and below.

## What to deliver

Working implementations of every exported function and method in the seven packages, with their names, signatures, types and fields unchanged. `go build ./...` compiles `selfcheck/api.go`, so a missing or changed declaration breaks the build. You may add files, unexported types and helpers in those seven directories, and rewrite the existing files however you like. You may use the module's existing dependencies (for example `github.com/gotd/ige` for AES-IGE, `github.com/go-faster/xor`, `golang.org/x/crypto`); you cannot add new ones.

The grader takes only the non-test `.go` files that sit directly in `proto/codec`, `mtproxy/obfuscated2`, `crypto`, `exchange`, `mtproto`, `mtproto/salts` and `rpc`. Every other file comes from the starting state, including `go.mod`, `go.sum`, the callers and your own `_test.go` files, so edits elsewhere are discarded. Write tests anywhere you like; they help you, not the score.

### proto/codec

Four codecs implement `Codec`, and three also implement `TaggedCodec`. Tags: abridged `0xef` (one byte; obfuscated tag `efefefef`), intermediate `eeeeeeee`, padded intermediate `dddddddd`. Full has no tag, and its `WriteHeader` and `ReadHeader` do nothing. `ReadHeader` reports a wrong tag as `ErrProtocolHeaderMismatch`.

- Abridged frame: length/4 as one byte when it is below 127, otherwise `0x7f` and length/4 in 3 little-endian bytes; then the payload.
- Intermediate: a 4-byte little-endian length, then the payload.
- Padded intermediate: as intermediate, with 0 to 3 random bytes appended and counted in the length. The reader drops the last (length mod 4) bytes.
- Full: total length (payload + 12), sequence number, payload, CRC32 (IEEE) of everything before it, all integers 4-byte little-endian. Each `*Full` counts written and read frames separately from 0. A read with the wrong sequence number or a bad CRC is an error.
- `Write` rejects an empty payload, a payload over 1<<24 bytes, and (except Full) a payload whose length is not a multiple of 4. On rejection it writes nothing.
- `Read` rejects a declared length of zero, one above 1<<24, or a truncated frame. A frame whose payload is exactly 4 bytes is a transport error: return `*ProtocolErr` whose `Code` is the negated little-endian int32 (-404 on the wire becomes 404). The stream stays usable after one.

### mtproxy/obfuscated2

`Handshake` builds and sends the 64-byte header and sets up both AES-256-CTR streams. `Write` and `Read` then encrypt and decrypt every byte. `Accept` is the server side: it reads the header, derives the same streams with their roles swapped and returns the protocol tag and DC id. The doc comment of `Obfuscated2` gives the key derivation, the rejected init patterns that force a redraw, the optional 16-byte secret (`SHA256(key + secret)`) and the header layout. The DC id is a little-endian int16 (negative ids are test DCs). `Read` must decrypt exactly the bytes it returns, even on short reads.

### crypto

- `Key.ID` and `Key.AuxHash`: the low and high 64 bits of SHA1(key).
- `Keys` and `MessageKey` (MTProto 2.0, SHA256-based, x = 0 client / 8 server); `OldKeys`, `KeysV1` and `MessageKeyV1` (MTProto 1.0, SHA1-based).
- `Cipher.Encrypt`: encodes the message data, appends random padding of 12 to 1024 bytes so that the plaintext length is a multiple of 16, computes msg_key and AES-256-IGE keys for the cipher's own side and writes `auth_key_id + msg_key + ciphertext` into the reset buffer. `Decrypt` and `DecryptFromBuffer` use the opposite side's keys and reject the cases the doc comment lists: wrong key id, length not a multiple of 16, msg_key mismatch, undecodable data, a negative or non-multiple-of-4 data length, padding over 1024 bytes.
- Wire types `EncryptedMessage`, `EncryptedMessageData` (including `EncodeWithoutCopy` with an inner `bin.Encoder`), `BindAuthKeyInner`, and `EncryptBindMessage` for `auth.bindTempAuthKey`.
- Key-exchange primitives: `RSAFingerprint`, `RSAPad`/`DecodeRSAPad` (RSA_PAD: data of at most 144 bytes, 256-byte result, decoded to the 192-byte data_with_padding), `RSAEncryptHashed`/`RSADecryptHashed`, `RSAPublicDecrypt`, `DecomposePQ`, `CheckGP`, `CheckDH`, `CheckDHParams`, `InRange`, `TempAESKeys` (nonces hashed at full width, leading zero bytes kept), `EncryptExchangeAnswer`/`DecryptExchangeAnswer`, `DataWithHash`/`GuessDataWithHash`, `NonceHash1`, `ServerSalt`.
- `DecomposePQ` must factor any product of two primes below 2^63 well within the per-case time limit (12 seconds). Trial division up to the square root is too slow on 62-bit inputs.

### exchange

`ClientExchange.Run` and `ServerExchange.Run` implement the auth key creation flow over a `transport.Conn` with plaintext messages (`proto.UnencryptedMessage`, msg_id from `proto.NewMessageID` with the clock and the sender's message type). Their doc comments list the contract, which the grader checks message by message:

- Both sides take all randomness from the `Exchanger`'s source and time from its clock. Temporary mode sends `p_q_inner_data_temp_dc` and sets `ExpiresAt` to clock now plus `expires_in`.
- Client: skip transport errors with code 404 while waiting for resPQ; pick the first configured key whose fingerprint the server lists, else return `ErrKeyFingerprintNotFound`; reject pq above 2^63, nonce or server_nonce mismatches, `server_DH_params_fail`, an undecryptable answer, parameters that fail `CheckDH` or `CheckDHParams`, a wrong `new_nonce_hash1`, `dh_gen_retry` and `dh_gen_fail`. Each check runs when its message arrives, and on failure `Run` returns without sending anything further.
- Server: accept `req_pq` and `req_pq_multi`, and answer a repeated one with a new resPQ; return `*UnexpectedEncryptedError` (key id plus a copy of the frame) for any frame with a non-zero auth_key_id; return `*ServerExchangeError` with code 404 when the RSA_PAD data or the client DH data cannot be decrypted or decoded, and 444 when the inner data names another DC.
- Both results hold the same auth key, its id and the same server salt.

### mtproto, mtproto/salts and rpc

The package comment of `mtproto` (`mtproto/doc.go`) is the contract for `Conn`; the doc comments of `rpc.Engine` and `salts.Salts` cover the rest. The grader runs your `Conn` against a scripted server and checks both what the server sees and what your calls return:

- Connecting: a new permanent key, or the stored `Options.Key` and `Options.Salt` with a fresh session id; with `EnablePFS`, a permanent and a temporary key on the same connection and a valid `auth.bindTempAuthKey` before `f` runs (a `boolFalse` answer makes `Run` fail); a dial error makes `Run` fail without calling `f`.
- Sending: msg_id strictly increasing and divisible by 4, one session id, the current salt, seq_no 2n+1 for each `Invoke` request and even for msgs_ack, ping and get_future_salts, gzip_packed above `CompressThreshold` (never when it is negative).
- Receiving: results (plain, gzip-packed, in containers), `rpc_error` as `*tgerr.Error`, `new_session_created` (salt, `Handler.OnSession`), `bad_server_salt` (one resend with the new salt), `bad_msg_notification` (the request fails), `future_salts`, acknowledgements of content-related server messages within `AckInterval`, updates to `Handler.OnMessage` once, and silently dropped messages with a wrong session, a stale, early or client-typed msg_id, or a repeated msg_id.
- Requests: resend with the same msg_id and seq_no every `RetryInterval` until acknowledged, nothing resent once acknowledged, `*rpc.RetryLimitReachedErr` after `MaxRetries`; `Ping` waits for its pong; a transport 404 creates a new key on the same connection and the pending request is answered under it.

## Building and checking your work

```
cd /app
go build ./...                      # must stay green: a broken build scores 0
bash selfcheck/run.sh               # build, discarded-file report, forbidden imports, samples, integration tests
go run ./selfcheck -v               # just the samples, listing each failure
go test ./transport/ ./tgtest/... ./telegram/... ./session/tdesktop/ ./crypto/srp/
```

`selfcheck/run.sh` mirrors the gates. It then runs 76 fixed vectors produced by a known-good implementation, round trips of your packages against themselves (codec write/read, obfuscated handshake/accept, encrypt/decrypt, RSA_PAD, exchange answer, a full key exchange in both modes), and the 34 integration tests the grader runs (listed in `selfcheck/integration.txt`). It prints a per-group estimate. The graded suite is larger and stricter: the same families with other inputs, every encoder checked by an independent decoder, both exchange roles against an independent peer, peers that misbehave at each step, and a scripted server that drives your `Conn` through every session scenario listed above. The samples pass on the reference solution; passing them does not guarantee a full score.

## Scoring

The grader rebuilds a clean tree (the starting state plus your non-test `.go` files in the seven directories) and works offline as an unprivileged user with a fresh build cache, `CGO_ENABLED=0`.

Hard gates. Each one scores exactly 0:

1. `go build ./...` fails on the clean tree. This includes `selfcheck/api.go`, so every exported declaration must keep its signature.
2. A file in the seven packages imports `unsafe`, `C`, `os/exec`, `syscall`, `plugin`, `runtime/cgo` or `golang.org/x/sys/...`, or uses a `//go:linkname` or cgo directive.
3. The toolchain under `/usr/local/go`, the module cache under `/go/pkg/mod` (`go mod verify`) or the generated package `/app/tg` differs from the starting state.

Then the score:

```
reward = 0.06 * codec + 0.06 * obfs + 0.14 * msg + 0.12 * hs + 0.22 * kex + 0.32 * sess + 0.08 * integration
```

Each term is the fraction of that group's cases passed: codec (130 cases), obfs (62), msg (178), hs (127), kex (58), sess (41), integration (34 tests). The denominators are fixed. A case passes only when its output equals the output of the reference implementation exactly. A case that errors, panics, crashes the case runner or runs past its time limit (12 to 60 seconds) fails. Outputs never depend on how much randomness your code reads or in what order: random-dependent results are checked through an independent decoder and stated properties (padding ranges, alignment, key equality). Each integration test runs alone with a 90-second timeout. The starting state scores 0; the reference solution scores 1.

## Time budget

You have 8 hours. The container clock does not show your remaining time; `/app/.timer` does. Run `cat /app/.timer/remaining_secs` before any long step. `alert_30min`, `alert_10min` and `alert_5min` appear in `/app/.timer` as the budget runs down.

## Constraints

- No network. Do not modify `/usr/local/go`, `/go/pkg/mod` or `/app/tg`; that is a hard gate, not a shortcut.
- Keep randomness on the readers you are given (`Cipher`'s source, the `rand` arguments, the `Exchanger`'s source). Use the clock you are given in `exchange` and `mtproto`.
- Keep `crypto` free of imports from `exchange`, `mtproto` or `telegram` (import cycles).

## Operating rules

Nobody will answer questions, so make the call yourself and keep going. A green `go build ./...` is the floor at every moment: the score is per case, so a half-finished package that compiles still earns its finished parts, and a tree that does not build earns nothing. A good order: codec, the crypto primitives against fixed vectors, the cipher, obfuscation, the two exchange flows, then the rpc engine and the session. Each layer has round trips and callers to test it with. When the selfcheck and the callers' tests pass, read the contract again and add tests for the error paths: the graded suite checks each one. Check `/app/.timer/remaining_secs` before long test runs. Keep the last 20 minutes for `bash selfcheck/run.sh` and a final clean build.
