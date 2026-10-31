package exchange

import (
	"context"
	"fmt"
)

// ServerExchangeError is returned when exchange fails due to
// some security or validation checks.
type ServerExchangeError struct {
	Code int32
	Err  error
}

// Error implements error.
func (s *ServerExchangeError) Error() string {
	return s.Err.Error()
}

// Unwrap implements error wrapper interface.
func (s *ServerExchangeError) Unwrap() error {
	return s.Err
}

// UnexpectedEncryptedError is returned by the server key-exchange flow when it
// reads a frame whose leading auth key id is non-zero while expecting an
// unencrypted exchange message. This means the peer is using an already
// established auth key instead of performing key exchange.
//
// The caller should resolve the key and handle Frame as an encrypted message
// rather than treating it as an exchange failure. In particular, callers must
// not blindly reply with auth_key_not_found (-404): clients such as Telegram
// Desktop treat a -404 on a temporary key as "key destroyed", discard it and
// re-run key exchange, which leads to a reconnect/key-exchange storm.
type UnexpectedEncryptedError struct {
	// AuthKeyID is the auth key id the encrypted frame was sent with.
	AuthKeyID [8]byte
	// Frame is the raw transport frame (the full encrypted message).
	Frame []byte
}

// Error implements error.
func (e *UnexpectedEncryptedError) Error() string {
	return fmt.Sprintf("unexpected encrypted message (auth key id %x) during key exchange", e.AuthKeyID)
}

// Run runs server-side flow.
//
// It answers the client's messages of https://core.telegram.org/mtproto/auth_key
// as the server: resPQ with the pq from its ServerRNG and the fingerprint of
// its key, server_DH_params_ok (g = 3, dh_prime and g_a from its ServerRNG,
// server_DH_inner_data encrypted with crypto.EncryptExchangeAnswer), and
// dh_gen_ok with new_nonce_hash1. Its plaintext messages carry msg_id =
// proto.NewMessageID(clock now, proto.MessageServerResponse).
//
// Contract:
//   - both req_pq (legacy) and req_pq_multi start the exchange; a further
//     req_pq or req_pq_multi received instead of req_DH_params is answered
//     with a new resPQ for the new nonce and the flow continues;
//   - any message read while expecting a plaintext message whose leading 8
//     bytes (auth_key_id) are not zero makes Run return
//     *UnexpectedEncryptedError carrying that auth key id and a copy of the
//     whole frame;
//   - encrypted_data that crypto.DecodeRSAPad rejects, a client_DH_inner_data
//     that cannot be decrypted or decoded, or an auth key that does not fit
//     in 256 bytes makes Run return *ServerExchangeError with Code
//     codec.CodeAuthKeyNotFound (404);
//   - a p_q_inner_data_dc or p_q_inner_data_temp_dc whose dc differs from the
//     Exchanger's dc makes Run return *ServerExchangeError with Code
//     codec.CodeWrongDC (444);
//   - on success the result holds the same auth key (with its id) as the
//     client and the server salt crypto.ServerSalt(new_nonce, server_nonce).
func (s ServerExchange) Run(ctx context.Context) (ServerExchangeResult, error) {
	return ServerExchangeResult{}, errNotImplemented
}
