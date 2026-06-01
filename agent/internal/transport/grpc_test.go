package transport

import (
	"context"
	"net"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"

	tunnelpb "github.com/nightwatch/proto/gen/go/tunnelpb"
)

type fakeServer struct {
	tunnelpb.UnimplementedTunnelServer
	received chan *tunnelpb.AgentMessage
}

func (f *fakeServer) Stream(s tunnelpb.Tunnel_StreamServer) error {
	for {
		m, err := s.Recv()
		if err != nil {
			return err
		}
		f.received <- m
		switch m.Kind.(type) {
		case *tunnelpb.AgentMessage_Hello:
			s.Send(&tunnelpb.RelayMessage{Kind: &tunnelpb.RelayMessage_HelloAck{HelloAck: &tunnelpb.HelloAck{SessionId: "x"}}})
		case *tunnelpb.AgentMessage_CameraOpen:
			s.Send(&tunnelpb.RelayMessage{Kind: &tunnelpb.RelayMessage_CameraAck{CameraAck: &tunnelpb.CameraAck{Accepted: true}}})
		}
	}
}

func newFake(t *testing.T) (string, chan *tunnelpb.AgentMessage, func()) {
	lis, _ := net.Listen("tcp", "127.0.0.1:0")
	srv := grpc.NewServer()
	rcv := make(chan *tunnelpb.AgentMessage, 16)
	tunnelpb.RegisterTunnelServer(srv, &fakeServer{received: rcv})
	go srv.Serve(lis)
	return lis.Addr().String(), rcv, func() { srv.Stop(); lis.Close() }
}

func TestGRPC_ConnectAndOpenCamera(t *testing.T) {
	addr, rcv, done := newFake(t)
	defer done()
	tp := NewGRPC(addr, "k", []grpc.DialOption{grpc.WithTransportCredentials(insecure.NewCredentials())})
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	require.NoError(t, tp.Connect(ctx))
	require.NoError(t, tp.OpenCamera("cam-1"))
	require.NoError(t, tp.SendFrame("cam-1", []byte("hi"), false))

	got := <-rcv
	require.NotNil(t, got.GetHello())
	got = <-rcv
	require.Equal(t, "cam-1", got.GetCameraOpen().CameraId)
	got = <-rcv
	require.Equal(t, []byte("hi"), got.GetFrame().Payload)

	require.NoError(t, tp.Close())
	require.Equal(t, "grpc", tp.Name())
}
