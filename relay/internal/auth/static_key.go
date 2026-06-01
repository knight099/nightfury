package auth

import (
	"context"
	"errors"

	"google.golang.org/grpc/metadata"
)

type StaticKey struct{ Key string }

func (s StaticKey) Verify(ctx context.Context) error {
	if s.Key == "" {
		return errors.New("auth not configured")
	}
	md, ok := metadata.FromIncomingContext(ctx)
	if !ok {
		return errors.New("no metadata")
	}
	got := md.Get("x-agent-key")
	if len(got) == 0 || got[0] != s.Key {
		return errors.New("invalid agent key")
	}
	return nil
}
