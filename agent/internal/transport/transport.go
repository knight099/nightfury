package transport

import "context"

// Transport abstracts an outbound tunnel from the agent to the relay.
type Transport interface {
	Connect(ctx context.Context) error
	OpenCamera(cameraID string) error
	SendFrame(cameraID string, payload []byte, keyframe bool) error
	Close() error
	Name() string
}
