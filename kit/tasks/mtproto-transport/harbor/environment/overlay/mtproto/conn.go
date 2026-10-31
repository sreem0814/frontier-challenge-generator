package mtproto

import (
	"context"

	"github.com/go-faster/errors"

	"github.com/gotd/td/bin"
	"github.com/gotd/td/crypto"
	"github.com/gotd/td/proto"
	"github.com/gotd/td/transport"
)

// errNotImplemented is returned until the session layer is rebuilt.
var errNotImplemented = errors.New("mtproto: not implemented")

// Handler will be called on received message from Telegram.
type Handler interface {
	// OnMessage receives every decrypted message that is not a service
	// message handled by Conn (see the package documentation), for example
	// updates. The buffer starts at the message's TL type id.
	OnMessage(b *bin.Buffer) error
	// OnSession is called with the current session after new_session_created.
	OnSession(session Session) error
}

// MessageIDSource is message id generator.
type MessageIDSource interface {
	New(t proto.MessageType) int64
}

// MessageBuf is message id buffer.
type MessageBuf interface {
	Consume(id int64) bool
}

// Cipher handles message encryption and decryption.
type Cipher interface {
	DecryptFromBuffer(k crypto.AuthKey, buf *bin.Buffer) (*crypto.EncryptedMessageData, error)
	Encrypt(key crypto.AuthKey, data crypto.EncryptedMessageData, b *bin.Buffer) error
}

// Dialer is an abstraction for MTProto transport connection creator.
type Dialer func(ctx context.Context) (transport.Conn, error)

// Conn represents a MTProto client to Telegram.
type Conn struct {
	dialer Dialer
	opt    Options
}

// New creates new unstarted connection. Unset options get the defaults of
// Options.setDefaults.
func New(dialer Dialer, opt Options) *Conn {
	opt.setDefaults()
	return &Conn{dialer: dialer, opt: opt}
}

// Run initializes MTProto connection to server and blocks until disconnection.
//
// It dials, creates the auth key(s) if needed (see the package
// documentation), starts the read, ack, ping and salt loops, then runs f.
// Run returns when f returns (nil when f returns nil), when ctx is done, or
// with an error when the connection fails. Run may be called once per Conn.
//
// When connection is ready, Handler.OnSession is called.
func (c *Conn) Run(ctx context.Context, f func(ctx context.Context) error) error {
	return errNotImplemented
}

// Invoke sends input as a content message and decodes the matching
// rpc_result into output. An rpc_error answer is returned as *tgerr.Error.
func (c *Conn) Invoke(ctx context.Context, input bin.Encoder, output bin.Decoder) error {
	return errNotImplemented
}

// Ping sends ping (a service message) and waits for the matching pong.
func (c *Conn) Ping(ctx context.Context) error {
	return errNotImplemented
}
