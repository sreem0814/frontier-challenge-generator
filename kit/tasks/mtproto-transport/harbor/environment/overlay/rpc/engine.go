package rpc

import (
	"context"

	"github.com/go-faster/errors"

	"github.com/gotd/td/bin"
)

// errNotImplemented is returned until the engine is rebuilt.
var errNotImplemented = errors.New("rpc: not implemented")

// Engine handles RPC requests.
//
// It sends each request through Send, resends it with the same msg_id and
// seq_no every RetryInterval until the server acknowledges it (NotifyAcks)
// or a result or error arrives, and returns *RetryLimitReachedErr after
// MaxRetries resends without acknowledgement. An acknowledged request then
// waits for its result (NotifyResult) or error (NotifyError) without further
// resends.
type Engine struct {
	send Send
	cfg  Options
}

// New creates new rpc Engine.
func New(send Send, cfg Options) *Engine {
	cfg.setDefaults()
	return &Engine{send: send, cfg: cfg}
}

// Request represents client RPC request.
type Request struct {
	MsgID  int64
	SeqNo  int32
	Input  bin.Encoder
	Output bin.Decoder
}

// Do performs RPC request.
//
// It returns nil after Output decoded the result, the error passed to
// NotifyError, the decode error, *RetryLimitReachedErr, ErrEngineClosed when
// the engine is closed before the call, or ctx.Err(). When ctx is done after
// the request was sent and before its result, the DropHandler is called with
// the request (rpc_drop_answer) before Do returns ctx.Err().
func (e *Engine) Do(ctx context.Context, req Request) error {
	return errNotImplemented
}

// NotifyResult notifies engine about received RPC response.
func (e *Engine) NotifyResult(msgID int64, b *bin.Buffer) error {
	return errNotImplemented
}

// NotifyError notifies engine about received RPC error.
func (e *Engine) NotifyError(msgID int64, rpcErr error) {}

// NotifyAcks notifies engine about received acknowledgements.
func (e *Engine) NotifyAcks(ids []int64) {}

// Close gracefully closes the engine: new calls fail with ErrEngineClosed
// and Close waits for pending ones.
func (e *Engine) Close() {}

// ForceClose forcibly closes the engine: pending calls return an error
// wrapping ErrEngineClosed (unless their result already arrived).
func (e *Engine) ForceClose() {}
