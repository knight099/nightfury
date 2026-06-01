package transport

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/nightwatch/relay/webrtcsignal"
)

func TestWebRTC_RoundTripFrame(t *testing.T) {
	signal := webrtcsignal.NewServerWithRegistry("test-key")
	ts := httptest.NewServer(signal)
	defer ts.Close()

	// sanity that we imported net/http
	_ = http.MethodPost

	w := NewWebRTC(ts.URL, "test-key")
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := w.Connect(ctx); err != nil {
		t.Fatalf("connect: %v", err)
	}
	defer w.Close()

	const cam = "cam-1"
	if err := w.OpenCamera(cam); err != nil {
		t.Fatalf("open camera: %v", err)
	}
	if err := w.SendFrame(cam, []byte("hello-frame"), true); err != nil {
		t.Fatalf("send frame: %v", err)
	}

	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		if signal.HasCamera(cam) && signal.FrameCount(cam) > 0 {
			return
		}
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatalf("expected at least one buffered frame in registry within 2s; haveCamera=%v frames=%d", signal.HasCamera(cam), signal.FrameCount(cam))
}
