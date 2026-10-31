package exchange

import (
	"context"

	"github.com/go-faster/errors"
)

// errNotImplemented is returned until the key exchange flows are rebuilt.
var errNotImplemented = errors.New("exchange: not implemented")

// Run runs client-side flow.
//
// It performs the whole auth key creation of
// https://core.telegram.org/mtproto/auth_key as the client, with plaintext
// messages over the Exchanger's connection: req_pq_multi, resPQ,
// req_DH_params (p_q_inner_data_dc for permanent keys,
// p_q_inner_data_temp_dc with expires_in for WithTempMode, encrypted with
// crypto.RSAPad under the first configured key whose fingerprint the server
// listed), server_DH_params_ok, set_client_DH_params (client_DH_inner_data
// with retry_id 0) and dh_gen_ok.
//
// Plaintext messages carry msg_id = proto.NewMessageID(clock now,
// proto.MessageFromClient); the server answers with MessageServerResponse ids.
//
// Contract:
//   - all randomness (nonces, the exponent b, padding, session id) comes from
//     the Exchanger's random source (WithRand);
//   - while waiting for resPQ, a transport error with code 404
//     (*codec.ProtocolErr) is skipped and the read is retried;
//   - Run returns ErrKeyFingerprintNotFound (errors.Is) when no configured
//     key matches the server's fingerprints;
//   - every check below runs as soon as its message arrives; when one fails,
//     Run returns the error without sending any further message;
//   - Run returns an error when a nonce or server_nonce in resPQ,
//     server_DH_params_ok, server_DH_inner_data or dh_gen_ok differs from the
//     one sent, when pq is above 2^63, when the server answers
//     server_DH_params_fail, dh_gen_retry or dh_gen_fail, when the encrypted
//     answer cannot be decrypted or decoded, when crypto.CheckDH rejects
//     (g, dh_prime), when crypto.CheckDHParams rejects (dh_prime, g, g_a,
//     g_b), or when new_nonce_hash1 does not match;
//   - on success the result holds the auth key (with its id), a random
//     session id, the server salt (crypto.ServerSalt(new_nonce,
//     server_nonce)) and, in temporary mode, ExpiresAt = clock now (Unix
//     seconds) + expires_in; in permanent mode ExpiresAt is 0.
func (c ClientExchange) Run(ctx context.Context) (ClientExchangeResult, error) {
	return ClientExchangeResult{}, errNotImplemented
}
