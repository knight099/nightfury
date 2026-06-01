package localui

import (
	"context"
	"encoding/json"
	"net/http/httptest"
	"strings"
	"testing"
)

type fakePairer struct {
	called bool
	paired bool
}

func (f *fakePairer) Pair(ctx context.Context, code string) error {
	f.called = true
	if code != "123456" {
		return errCodeFmt
	}
	f.paired = true
	return nil
}

func (f *fakePairer) IsPaired() bool { return f.paired }

func TestPairHandlerSuccess(t *testing.T) {
	fp := &fakePairer{}
	h := newHandlers(fp)
	req := httptest.NewRequest("POST", "/api/pair", strings.NewReader(`{"code":"123456"}`))
	rr := httptest.NewRecorder()
	h.Pair(rr, req)
	if rr.Code != 200 {
		t.Fatalf("status %d body=%s", rr.Code, rr.Body.String())
	}
	if !fp.called {
		t.Fatal("Pair not called")
	}
}

func TestPairHandlerBadCode(t *testing.T) {
	h := newHandlers(&fakePairer{})
	req := httptest.NewRequest("POST", "/api/pair", strings.NewReader(`{"code":"abc"}`))
	rr := httptest.NewRecorder()
	h.Pair(rr, req)
	if rr.Code != 400 {
		t.Fatalf("status %d", rr.Code)
	}
}

func TestStatusHandler(t *testing.T) {
	h := newHandlers(&fakePairer{})
	req := httptest.NewRequest("GET", "/api/status", nil)
	rr := httptest.NewRecorder()
	h.Status(rr, req)
	var body map[string]any
	if err := json.NewDecoder(rr.Body).Decode(&body); err != nil {
		t.Fatal(err)
	}
	if _, ok := body["paired"]; !ok {
		t.Fatal("missing paired field")
	}
}
