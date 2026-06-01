package grpc_server

import (
	"errors"
	"io"
	"log/slog"

	tunnelpb "github.com/nightwatch/proto/gen/go/tunnelpb"
	"github.com/nightwatch/relay/internal/auth"
	"github.com/nightwatch/relay/internal/republish"
)

type Server struct {
	tunnelpb.UnimplementedTunnelServer
	Registry *republish.Registry
	Auth     auth.AgentAuthenticator
	BufCap   int
}

func (s *Server) Stream(stream tunnelpb.Tunnel_StreamServer) error {
	if err := s.Auth.Verify(stream.Context()); err != nil {
		return err
	}
	registered := map[string]bool{}
	defer func() {
		for id := range registered {
			s.Registry.Unregister(id)
		}
	}()

	for {
		msg, err := stream.Recv()
		if errors.Is(err, io.EOF) {
			return nil
		}
		if err != nil {
			return err
		}
		switch k := msg.Kind.(type) {
		case *tunnelpb.AgentMessage_Hello:
			if err := stream.Send(&tunnelpb.RelayMessage{Kind: &tunnelpb.RelayMessage_HelloAck{HelloAck: &tunnelpb.HelloAck{SessionId: "s-1"}}}); err != nil {
				return err
			}
		case *tunnelpb.AgentMessage_CameraOpen:
			id := k.CameraOpen.CameraId
			pub := republish.NewPublisher(id, s.BufCap)
			if err := s.Registry.RegisterErr(id, pub); err != nil {
				_ = stream.Send(&tunnelpb.RelayMessage{Kind: &tunnelpb.RelayMessage_CameraAck{CameraAck: &tunnelpb.CameraAck{CameraId: id, Accepted: false, Reason: err.Error()}}})
				continue
			}
			registered[id] = true
			_ = stream.Send(&tunnelpb.RelayMessage{Kind: &tunnelpb.RelayMessage_CameraAck{CameraAck: &tunnelpb.CameraAck{CameraId: id, Accepted: true}}})
		case *tunnelpb.AgentMessage_Frame:
			if pub, ok := s.Registry.Get(k.Frame.CameraId); ok {
				pub.Frames.Push(k.Frame.Payload)
			}
		case *tunnelpb.AgentMessage_CameraClose:
			s.Registry.Unregister(k.CameraClose.CameraId)
			delete(registered, k.CameraClose.CameraId)
		case *tunnelpb.AgentMessage_Heartbeat:
			_ = stream.Send(&tunnelpb.RelayMessage{Kind: &tunnelpb.RelayMessage_Pong{Pong: &tunnelpb.Pong{MonotonicUs: k.Heartbeat.MonotonicUs}}})
		default:
			slog.Warn("unknown agent message")
		}
	}
}
