// Package mtproto implements MTProto connection.
//
// Conn is the client side of an MTProto 2.0 session over a transport.Conn
// returned by the Dialer. The behaviour the rest of the module relies on:
//
// Connecting. Run dials once. Without a stored key (Options.Key) it runs a
// permanent key exchange (exchange package, Options.DC, Options.PublicKeys,
// Options.Random, Options.Clock) and takes the session id and server salt
// from its result. With a stored key it uses Options.Key and Options.Salt
// and draws a new random session id. With EnablePFS it creates a permanent
// key (unless Options.PermKey or Options.Key holds one), then a temporary key
// (temporary exchange mode, TempKeyTTL seconds) on the same connection, uses
// the temporary key for all traffic, and binds it before running f with
// auth.bindTempAuthKey: perm_auth_key_id, a random nonce, expires_at and
// crypto.EncryptBindMessage (bind_auth_key_inner with the temporary key id,
// the permanent key id, the temporary session id and expires_at, encrypted
// under the permanent key with the bind request's own msg_id). A boolFalse
// answer makes Run fail before f is called. A dial or key exchange failure
// makes Run return an error without calling f.
//
// Sending. Every message is encrypted with crypto.Cipher semantics
// (Options.Cipher, client side) with the current salt and session id.
// msg_id comes from Options.MessageID (strictly increasing, divisible by 4).
// seq_no is 2*n for a message that is not content-related and 2*n+1 for a
// content-related one, where n counts the content-related messages sent
// before it in the session. Invoke requests and auth.bindTempAuthKey are
// content-related; msgs_ack, ping, ping_delay_disconnect and
// get_future_salts are sent as not content-related. A payload whose encoding
// is longer than CompressThreshold bytes (default 1024) is sent as
// gzip_packed; a negative CompressThreshold disables compression.
//
// Receiving. Messages that fail to decrypt are an error; messages with
// another session id, a msg_id that is not from the server (msg_id mod 4 is
// not 1 or 3), created more than 300 seconds in the past or 30 seconds in
// the future (Options.Clock), or a msg_id equal to the previous accepted one
// are dropped silently. Content-related messages (odd seq_no) are
// acknowledged with msgs_ack within AckInterval, or as soon as AckBatchSize
// ids are waiting. msg_container is unpacked and each message handled;
// gzip_packed is unpacked wherever it appears, including inside rpc_result.
// rpc_result completes the matching request (rpc_error becomes *tgerr.Error),
// msgs_ack marks requests acknowledged, pong completes Ping,
// new_session_created stores its server_salt and calls Handler.OnSession,
// bad_server_salt (code 48) stores the new salt and sends the request again,
// once, bad_msg_notification fails the request with an error,
// future_salts are stored (salts package) and the salt valid 5 minutes from
// now is used for later messages, msg_detailed_info is ignored, and
// everything else goes to Handler.OnMessage. After new_session_created Conn
// sends get_future_salts and repeats it every SaltFetchInterval.
//
// Transport errors. A transport error with code 404 (*codec.ProtocolErr)
// means the server forgot the key: without PFS, Conn creates a new key on
// the same connection and requests that were not answered are sent again
// under it by the rpc engine; with PFS, Run returns an error wrapping
// ErrPFSReconnectRequired.
//
// Requests. Invoke uses the rpc engine (rpc package): resend with the same
// msg_id and seq_no every RetryInterval until acknowledged, at most
// MaxRetries times, then *rpc.RetryLimitReachedErr. When the caller's
// context ends after the request was sent, rpc_drop_answer is sent for it.
// Ping sends ping and waits for pong; the ping loop sends
// ping_delay_disconnect every PingInterval and Run fails when no pong arrives
// within PingTimeout.
package mtproto
