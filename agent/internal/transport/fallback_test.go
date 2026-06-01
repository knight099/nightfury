package transport

import (
	"errors"
	"testing"

	"github.com/stretchr/testify/require"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

func TestFallback_AuthErrorDoesNotTriggerFallback(t *testing.T) {
	d := &Decider{}
	authErr := status.Error(codes.Unauthenticated, "bad key")
	d.Record(authErr)
	require.False(t, d.ShouldFallback())
}

func TestFallback_ThreeConnectErrorsTriggers(t *testing.T) {
	d := &Decider{}
	netErr := errors.New("connection refused")
	for i := 0; i < 3; i++ {
		d.Record(netErr)
	}
	require.True(t, d.ShouldFallback())
}

func TestFallback_OneSuccessResetsCounter(t *testing.T) {
	d := &Decider{}
	netErr := errors.New("connection refused")
	d.Record(netErr)
	d.Record(netErr)
	d.RecordSuccess()
	d.Record(netErr)
	require.False(t, d.ShouldFallback())
}
