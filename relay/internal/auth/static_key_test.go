package auth

import (
	"context"
	"testing"

	"github.com/stretchr/testify/require"
	"google.golang.org/grpc/metadata"
)

func TestStaticKey_Accepts(t *testing.T) {
	authn := StaticKey{Key: "secret"}
	md := metadata.Pairs("x-agent-key", "secret")
	ctx := metadata.NewIncomingContext(context.Background(), md)
	require.NoError(t, authn.Verify(ctx))
}

func TestStaticKey_RejectsWrong(t *testing.T) {
	authn := StaticKey{Key: "secret"}
	md := metadata.Pairs("x-agent-key", "wrong")
	ctx := metadata.NewIncomingContext(context.Background(), md)
	require.Error(t, authn.Verify(ctx))
}

func TestStaticKey_RejectsMissing(t *testing.T) {
	authn := StaticKey{Key: "secret"}
	require.Error(t, authn.Verify(context.Background()))
}
