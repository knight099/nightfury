package rtsp

import (
	"context"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
)

func TestClient_InvalidURLReturnsError(t *testing.T) {
	c := &Client{URL: "rtsp://127.0.0.1:1/"}
	ctx, cancel := context.WithTimeout(context.Background(), 500*time.Millisecond)
	defer cancel()
	err := c.Run(ctx)
	require.Error(t, err)
}
