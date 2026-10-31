package exchange

import (
	"time"

	"github.com/gotd/td/clock"
	"github.com/gotd/td/proto"
	"github.com/gotd/td/transport"
)

// unencryptedWriter sends and receives the plaintext messages of the key
// exchange (auth_key_id = 0, msg_id, message_data_length, message_data; see
// proto.UnencryptedMessage) over conn. input is the message type expected
// from the peer, output the type of messages sent.
type unencryptedWriter struct {
	clock   clock.Clock
	conn    transport.Conn
	timeout time.Duration
	input   proto.MessageType
	output  proto.MessageType
}
