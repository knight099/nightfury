package grpc_server

import (
	"context"
	"net"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"

	tunnelpb "github.com/nightwatch/proto/gen/go/tunnelpb"
	"github.com/nightwatch/relay/internal/auth"
	"github.com/nightwatch/relay/internal/republish"
)

func newServer(t *testing.T) (tunnelpb.TunnelClient, *republish.Registry, func()) {
	lis, err := net.Listen("tcp", "127.0.0.1:0")
	require.NoError(t, err)

	reg := republish.NewRegistry()
	srv := grpc.NewServer()
	s := &Server{Registry: reg, Auth: auth.StaticKey{Key: "k"}, BufCap: 16}
	tunnelpb.RegisterTunnelServer(srv, s)
	go srv.Serve(lis)

	conn, err := grpc.NewClient(lis.Addr().String(), grpc.WithTransportCredentials(insecure.NewCredentials()))
	require.NoError(t, err)
	cli := tunnelpb.NewTunnelClient(conn)
	return cli, reg, func() { conn.Close(); srv.Stop(); lis.Close() }
}

func TestStream_HelloAuthAccepted(t *testing.T) {
	cli, _, done := newServer(t)
	defer done()
	ctx := metadata.NewOutgoingContext(context.Background(), metadata.Pairs("x-agent-key", "k"))
	stream, err := cli.Stream(ctx)
	require.NoError(t, err)
	require.NoError(t, stream.Send(&tunnelpb.AgentMessage{Kind: &tunnelpb.AgentMessage_Hello{Hello: &tunnelpb.Hello{AgentVersion: "test"}}}))
	got, err := stream.Recv()
	require.NoError(t, err)
	require.NotNil(t, got.GetHelloAck())
}

func TestStream_FrameRegistersPublisher(t *testing.T) {
	cli, reg, done := newServer(t)
	defer done()
	ctx := metadata.NewOutgoingContext(context.Background(), metadata.Pairs("x-agent-key", "k"))
	stream, err := cli.Stream(ctx)
	require.NoError(t, err)
	stream.Send(&tunnelpb.AgentMessage{Kind: &tunnelpb.AgentMessage_Hello{Hello: &tunnelpb.Hello{}}})
	_, _ = stream.Recv()
	stream.Send(&tunnelpb.AgentMessage{Kind: &tunnelpb.AgentMessage_CameraOpen{CameraOpen: &tunnelpb.CameraOpen{CameraId: "cam-1"}}})
	_, _ = stream.Recv()
	stream.Send(&tunnelpb.AgentMessage{Kind: &tunnelpb.AgentMessage_Frame{Frame: &tunnelpb.Frame{CameraId: "cam-1", Payload: []byte("hello")}}})

	time.Sleep(100 * time.Millisecond)
	pub, ok := reg.Get("cam-1")
	require.True(t, ok)
	require.GreaterOrEqual(t, pub.Frames.Len(), 1)
}

func TestStream_RejectsBadAuth(t *testing.T) {
	cli, _, done := newServer(t)
	defer done()
	ctx := metadata.NewOutgoingContext(context.Background(), metadata.Pairs("x-agent-key", "wrong"))
	stream, err := cli.Stream(ctx)
	require.NoError(t, err)
	require.NoError(t, stream.Send(&tunnelpb.AgentMessage{Kind: &tunnelpb.AgentMessage_Hello{Hello: &tunnelpb.Hello{}}}))
	_, err = stream.Recv()
	require.Error(t, err)
}
