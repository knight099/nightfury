package supervisor

import (
	"testing"
	"time"

	"github.com/stretchr/testify/require"
)

func TestNextBackoff_DoublesUpToCap(t *testing.T) {
	require.Equal(t, 2*time.Second, nextBackoff(1*time.Second))
	require.Equal(t, 30*time.Second, nextBackoff(20*time.Second))
	require.Equal(t, 30*time.Second, nextBackoff(30*time.Second))
}
