package republish

import (
	"testing"

	"github.com/stretchr/testify/require"
)

func TestRegistry_RegisterAndGet(t *testing.T) {
	reg := NewRegistry()
	pub := NewPublisher("cam-1", 64)
	reg.Register("cam-1", pub)

	got, ok := reg.Get("cam-1")
	require.True(t, ok)
	require.Same(t, pub, got)
}

func TestRegistry_DuplicateRegisterRejected(t *testing.T) {
	reg := NewRegistry()
	pub1 := NewPublisher("cam-1", 64)
	pub2 := NewPublisher("cam-1", 64)
	require.NoError(t, reg.RegisterErr("cam-1", pub1))
	require.Error(t, reg.RegisterErr("cam-1", pub2))
}

func TestRegistry_Unregister(t *testing.T) {
	reg := NewRegistry()
	pub := NewPublisher("cam-1", 64)
	reg.Register("cam-1", pub)
	reg.Unregister("cam-1")
	_, ok := reg.Get("cam-1")
	require.False(t, ok)
}
