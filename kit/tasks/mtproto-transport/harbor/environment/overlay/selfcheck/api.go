package main

// Compile-time check of the exported API of the four packages. `go build ./...` fails here when a
// function, method, type, field, variable or constant is missing or has a different signature.

import (
	"context"
	"crypto/rsa"
	"io"
	"math/big"
	"time"

	"github.com/go-faster/jx"
	"github.com/gotd/log"

	"github.com/gotd/td/bin"
	"github.com/gotd/td/clock"
	"github.com/gotd/td/crypto"
	"github.com/gotd/td/exchange"
	"github.com/gotd/td/mt"
	"github.com/gotd/td/mtproto"
	"github.com/gotd/td/mtproto/salts"
	"github.com/gotd/td/mtproxy"
	"github.com/gotd/td/mtproxy/obfuscated2"
	"github.com/gotd/td/proto"
	"github.com/gotd/td/proto/codec"
	"github.com/gotd/td/rpc"
	"github.com/gotd/td/transport"
)

var (
	// proto/codec
	_ codec.Codec       = codec.Abridged{}
	_ codec.TaggedCodec = codec.Abridged{}
	_ codec.TaggedCodec = codec.Intermediate{}
	_ codec.TaggedCodec = codec.PaddedIntermediate{}
	_ codec.Codec       = &codec.Full{}
	_ codec.Codec       = codec.NoHeader{Codec: codec.Intermediate{}}
	_ [1]byte           = codec.AbridgedClientStart
	_ [4]byte           = codec.IntermediateClientStart
	_ [4]byte           = codec.PaddedIntermediateClientStart
	_ error             = codec.ErrProtocolHeaderMismatch
	_ error             = &codec.ProtocolErr{Code: codec.CodeAuthKeyNotFound + codec.CodeWrongDC + codec.CodeTransportFlood}

	// mtproxy/obfuscated2
	_ func(io.Reader, io.ReadWriter) *obfuscated2.Obfuscated2                    = obfuscated2.NewObfuscated2
	_ func(*obfuscated2.Obfuscated2, [4]byte, int, mtproxy.Secret) error          = (*obfuscated2.Obfuscated2).Handshake
	_ io.ReadWriter                                                               = (*obfuscated2.Obfuscated2)(nil)
	_ func(io.ReadWriter, []byte) (io.ReadWriter, obfuscated2.Metadata, error)    = obfuscated2.Accept
	_                                                                             = obfuscated2.Metadata{Protocol: [4]byte{}, DC: uint16(0)}

	// crypto: keys and message crypto
	_ func(crypto.Key) [8]byte                                                    = crypto.Key.ID
	_ func(crypto.Key) [8]byte                                                    = crypto.Key.AuxHash
	_ func(crypto.Key) crypto.AuthKey                                             = crypto.Key.WithID
	_ func(crypto.Key) bool                                                       = crypto.Key.Zero
	_                                                                             = crypto.AuthKey{Value: crypto.Key{}, ID: [8]byte{}}
	_ func(*crypto.AuthKey, *jx.Decoder) error                                    = (*crypto.AuthKey).DecodeJSON
	_ func(crypto.AuthKey, *jx.Encoder) error                                     = crypto.AuthKey.EncodeJSON
	_ func(crypto.AuthKey) int64                                                  = crypto.AuthKey.IntID
	_ func(*crypto.AuthKey, int64)                                                = (*crypto.AuthKey).SetIntID
	_ func(crypto.AuthKey) log.Attr                                               = crypto.AuthKey.LogAttr
	_ func(crypto.Side) crypto.Side                                               = crypto.Side.DecryptSide
	_                                                                             = [2]crypto.Side{crypto.Client, crypto.Server}
	_ func(crypto.Key, bin.Int128, crypto.Side) (bin.Int256, bin.Int256)          = crypto.Keys
	_ func(crypto.Key, []byte, crypto.Side) bin.Int128                            = crypto.MessageKey
	_ func(crypto.Key, bin.Int128, crypto.Side) (bin.Int256, bin.Int256)          = crypto.OldKeys
	_ func([]byte) bin.Int128                                                     = crypto.MessageKeyV1
	_ func(crypto.Key, bin.Int128) (bin.Int256, bin.Int256)                       = crypto.KeysV1
	_ func(io.Reader) crypto.Cipher                                               = crypto.NewClientCipher
	_ func(io.Reader) crypto.Cipher                                               = crypto.NewServerCipher
	_ func(crypto.Cipher) io.Reader                                               = crypto.Cipher.Rand
	_ func(crypto.Cipher, crypto.AuthKey, crypto.EncryptedMessageData, *bin.Buffer) error = crypto.Cipher.Encrypt
	_ func(crypto.Cipher, crypto.AuthKey, *bin.Buffer) (*crypto.EncryptedMessageData, error) = crypto.Cipher.DecryptFromBuffer
	_ func(crypto.Cipher, crypto.AuthKey, *crypto.EncryptedMessage) (*crypto.EncryptedMessageData, error) = crypto.Cipher.Decrypt
	_ = crypto.EncryptedMessage{AuthKeyID: [8]byte{}, MsgKey: bin.Int128{}, EncryptedData: nil}
	_ func(*crypto.EncryptedMessage, *bin.Buffer) error = (*crypto.EncryptedMessage).Decode
	_ func(*crypto.EncryptedMessage, *bin.Buffer) error = (*crypto.EncryptedMessage).DecodeWithoutCopy
	_ func(crypto.EncryptedMessage, *bin.Buffer) error  = crypto.EncryptedMessage.Encode
	_ = crypto.EncryptedMessageData{Salt: 0, SessionID: 0, MessageID: 0, SeqNo: int32(0), MessageDataLen: int32(0),
		MessageDataWithPadding: nil, Message: bin.Encoder(nil)}
	_ func(crypto.EncryptedMessageData, *bin.Buffer) error  = crypto.EncryptedMessageData.Encode
	_ func(crypto.EncryptedMessageData, *bin.Buffer) error  = crypto.EncryptedMessageData.EncodeWithoutCopy
	_ func(*crypto.EncryptedMessageData, *bin.Buffer) error = (*crypto.EncryptedMessageData).Decode
	_ func(*crypto.EncryptedMessageData, *bin.Buffer) error = (*crypto.EncryptedMessageData).DecodeWithoutCopy
	_ func(*crypto.EncryptedMessageData) []byte             = (*crypto.EncryptedMessageData).Data
	_ func([]byte) []byte                                   = crypto.GuessDataWithHash
	_ func([]byte, io.Reader) ([]byte, error)               = crypto.DataWithHash
	_ uint32                                                = crypto.BindAuthKeyInnerTypeID
	_ = crypto.BindAuthKeyInner{Nonce: 0, TempAuthKeyID: 0, PermAuthKeyID: 0, TempSessionID: 0, ExpiresAt: int(0)}
	_ bin.Object = (*crypto.BindAuthKeyInner)(nil)
	_ func(io.Reader, crypto.AuthKey, int64, *crypto.BindAuthKeyInner) ([]byte, error) = crypto.EncryptBindMessage

	// crypto: key exchange primitives
	_ int                                                    = crypto.RSAKeyBits
	_ func(*rsa.PublicKey, []byte) ([]byte, error)           = crypto.RSAPublicDecrypt
	_ func(*rsa.PublicKey) int64                             = crypto.RSAFingerprint
	_ func([]byte, *rsa.PublicKey, io.Reader) ([]byte, error) = crypto.RSAEncryptHashed
	_ func([]byte, *rsa.PrivateKey) ([]byte, error)          = crypto.RSADecryptHashed
	_ func([]byte, *rsa.PublicKey, io.Reader) ([]byte, error) = crypto.RSAPad
	_ func([]byte, *rsa.PrivateKey) ([]byte, error)          = crypto.DecodeRSAPad
	_ func(*big.Int, io.Reader) (*big.Int, *big.Int, error)  = crypto.DecomposePQ
	_ func(int, *big.Int) error                              = crypto.CheckDH
	_ func(int, *big.Int) error                              = crypto.CheckGP
	_ func(*big.Int, *big.Int, *big.Int, *big.Int) error     = crypto.CheckDHParams
	_ func(*big.Int, *big.Int, *big.Int) bool                = crypto.InRange
	_ func(*big.Int, *big.Int) ([]byte, []byte)              = crypto.TempAESKeys
	_ func([]byte, []byte, []byte) ([]byte, error)           = crypto.DecryptExchangeAnswer
	_ func(io.Reader, []byte, []byte, []byte) ([]byte, error) = crypto.EncryptExchangeAnswer
	_ func(bin.Int256, crypto.Key) bin.Int128                = crypto.NonceHash1
	_ func(bin.Int256, bin.Int128) int64                     = crypto.ServerSalt
	_ func(io.Reader) (int64, error)                         = crypto.NewSessionID
	_ func(*big.Int, []byte) bool                            = crypto.FillBytes
	_ func(*big.Int) bool                                    = crypto.Prime
	_ func(...[]byte) []byte                                 = crypto.SHA256

	// exchange
	_ func(transport.Conn, int) exchange.Exchanger                 = exchange.NewExchanger
	_ func(exchange.Exchanger, clock.Clock) exchange.Exchanger     = exchange.Exchanger.WithClock
	_ func(exchange.Exchanger, io.Reader) exchange.Exchanger       = exchange.Exchanger.WithRand
	_ func(exchange.Exchanger, time.Duration) exchange.Exchanger   = exchange.Exchanger.WithTimeout
	_ func(exchange.Exchanger, int) exchange.Exchanger             = exchange.Exchanger.WithTempMode
	_ func(exchange.Exchanger, []exchange.PublicKey) exchange.ClientExchange = exchange.Exchanger.Client
	_ func(exchange.Exchanger, exchange.PrivateKey) exchange.ServerExchange  = exchange.Exchanger.Server
	_ func(exchange.ClientExchange, context.Context) (exchange.ClientExchangeResult, error) = exchange.ClientExchange.Run
	_ func(exchange.ServerExchange, context.Context) (exchange.ServerExchangeResult, error) = exchange.ServerExchange.Run
	_ = exchange.ClientExchangeResult{AuthKey: crypto.AuthKey{}, SessionID: 0, ServerSalt: 0, ExpiresAt: 0}
	_ = exchange.ServerExchangeResult{Key: crypto.AuthKey{}, ServerSalt: 0}
	_ error = &exchange.ServerExchangeError{Code: 0, Err: nil}
	_ error = &exchange.UnexpectedEncryptedError{AuthKeyID: [8]byte{}, Frame: nil}
	_ error = exchange.ErrKeyFingerprintNotFound
	_ = exchange.PublicKey{RSA: (*rsa.PublicKey)(nil)}
	_ = exchange.PrivateKey{RSA: (*rsa.PrivateKey)(nil)}

	// mtproto
	_ func(mtproto.Dialer, mtproto.Options) *mtproto.Conn                              = mtproto.New
	_ func(*mtproto.Conn, context.Context, func(context.Context) error) error          = (*mtproto.Conn).Run
	_ func(*mtproto.Conn, context.Context, bin.Encoder, bin.Decoder) error             = (*mtproto.Conn).Invoke
	_ func(*mtproto.Conn, context.Context) error                                       = (*mtproto.Conn).Ping
	_ mtproto.Dialer                                                                   = func(context.Context) (transport.Conn, error) { return nil, nil }
	_ mtproto.Cipher                                                                   = crypto.Cipher{}
	_ mtproto.MessageIDSource                                                          = proto.NewMessageIDGen(time.Now)
	_ mtproto.MessageBuf                                                               = proto.NewMessageIDBuf(1)
	_ = mtproto.Session{ID: 0, Key: crypto.AuthKey{}, Salt: 0, PermKey: crypto.AuthKey{}}
	_ = mtproto.Options{DC: 0, PublicKeys: nil, Random: nil, Logger: nil, Handler: mtproto.Handler(nil), AckBatchSize: 0,
		AckInterval: 0, RetryInterval: 0, MaxRetries: 0, DialTimeout: 0, ExchangeTimeout: 0, SaltFetchInterval: 0,
		PingTimeout: 0, PingInterval: 0, RequestTimeout: nil, CompressThreshold: 0, MessageID: nil, Clock: nil,
		Types: nil, Key: crypto.AuthKey{}, PermKey: crypto.AuthKey{}, Salt: 0, EnablePFS: false, TempKeyTTL: 0,
		Tracer: nil, Cipher: nil}
	_ error = mtproto.ErrPFSReconnectRequired
	_ error = mtproto.ErrPFSDropKeysRequired

	// mtproto/salts
	_ func(*salts.Salts, time.Time) (int64, bool) = (*salts.Salts).Get
	_ func(*salts.Salts, []mt.FutureSalt)        = (*salts.Salts).Store
	_ func(*salts.Salts)                          = (*salts.Salts).Reset

	// rpc
	_ func(rpc.Send, rpc.Options) *rpc.Engine                    = rpc.New
	_ func(*rpc.Engine, context.Context, rpc.Request) error      = (*rpc.Engine).Do
	_ func(*rpc.Engine, int64, *bin.Buffer) error                = (*rpc.Engine).NotifyResult
	_ func(*rpc.Engine, int64, error)                            = (*rpc.Engine).NotifyError
	_ func(*rpc.Engine, []int64)                                 = (*rpc.Engine).NotifyAcks
	_ func(*rpc.Engine)                                          = (*rpc.Engine).Close
	_ func(*rpc.Engine)                                          = (*rpc.Engine).ForceClose
	_ = rpc.Request{MsgID: 0, SeqNo: int32(0), Input: bin.Encoder(nil), Output: bin.Decoder(nil)}
	_ = rpc.Options{RetryInterval: 0, MaxRetries: 0, Logger: nil, Clock: nil, DropHandler: rpc.NopDrop}
	_ rpc.Send  = rpc.NopSend
	_ error     = &rpc.RetryLimitReachedErr{Retries: 0}
	_ error     = rpc.ErrEngineClosed
)
