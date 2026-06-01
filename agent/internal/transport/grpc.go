package transport

import (
	"context"
	"errors"
	"sync"

	"google.golang.org/grpc"
	"google.golang.org/grpc/metadata"

	tunnelpb "github.com/nightwatch/proto/gen/go/tunnelpb"
)

// GRPC is a Transport implementation that runs over a bidi gRPC stream.
type GRPC struct {
	addr     string
	key      string
	dialOpts []grpc.DialOption

	mu     sync.Mutex
	conn   *grpc.ClientConn
	client tunnelpb.TunnelClient
	stream tunnelpb.Tunnel_StreamClient
}

func NewGRPC(addr, key string, dialOpts []grpc.DialOption) *GRPC {
	return &GRPC{addr: addr, key: key, dialOpts: dialOpts}
}

func (g *GRPC) Name() string { return "grpc" }

func (g *GRPC) Connect(ctx context.Context) error {
	conn, err := grpc.NewClient(g.addr, g.dialOpts...)
	if err != nil {
		return err
	}
	cli := tunnelpb.NewTunnelClient(conn)
	md := metadata.Pairs("x-agent-token", g.key)
	streamCtx := metadata.NewOutgoingContext(ctx, md)
	stream, err := cli.Stream(streamCtx)
	if err != nil {
		conn.Close()
		return err
	}
	if err := stream.Send(&tunnelpb.AgentMessage{Kind: &tunnelpb.AgentMessage_Hello{Hello: &tunnelpb.Hello{AgentVersion: "0.1.0"}}}); err != nil {
		conn.Close()
		return err
	}
	if _, err := stream.Recv(); err != nil {
		conn.Close()
		return err
	}
	g.mu.Lock()
	g.conn, g.client, g.stream = conn, cli, stream
	g.mu.Unlock()
	return nil
}

func (g *GRPC) OpenCamera(id string) error {
	g.mu.Lock()
	s := g.stream
	g.mu.Unlock()
	if s == nil {
		return errors.New("not connected")
	}
	if err := s.Send(&tunnelpb.AgentMessage{Kind: &tunnelpb.AgentMessage_CameraOpen{CameraOpen: &tunnelpb.CameraOpen{CameraId: id}}}); err != nil {
		return err
	}
	_, err := s.Recv()
	return err
}

func (g *GRPC) SendFrame(id string, payload []byte, keyframe bool) error {
	g.mu.Lock()
	s := g.stream
	g.mu.Unlock()
	if s == nil {
		return errors.New("not connected")
	}
	return s.Send(&tunnelpb.AgentMessage{Kind: &tunnelpb.AgentMessage_Frame{Frame: &tunnelpb.Frame{CameraId: id, Payload: payload, Keyframe: keyframe}}})
}

func (g *GRPC) Close() error {
	g.mu.Lock()
	defer g.mu.Unlock()
	if g.stream != nil {
		_ = g.stream.CloseSend()
	}
	if g.conn != nil {
		return g.conn.Close()
	}
	return nil
}
