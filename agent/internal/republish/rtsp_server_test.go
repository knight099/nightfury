package republish

import (
	"context"
	"net"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
)

func TestRTSPServer_StartsAndAcceptsConnection(t *testing.T) {
	reg := NewRegistry()
	pub := NewPublisher("cam-1", 32)
	for _, b := range [][]byte{[]byte("frame1"), []byte("frame2")} {
		pub.Frames.Push(b)
	}
	reg.Register("cam-1", pub)

	srv := NewRTSPServer(reg, "127.0.0.1:0")
	go func() { _ = srv.Run(context.Background()) }()

	require.Eventually(t, func() bool {
		return srv.Addr() != ""
	}, time.Second, 10*time.Millisecond)

	c, err := net.DialTimeout("tcp", srv.Addr(), time.Second)
	require.NoError(t, err)
	_ = c.Close()
}
