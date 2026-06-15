package discovery

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestReportPostsDevicesWithToken(t *testing.T) {
	var gotAuth string
	var gotPayload reportPayload
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/agents/me/discovered" {
			t.Errorf("unexpected path %q", r.URL.Path)
		}
		gotAuth = r.Header.Get("Authorization")
		if err := json.NewDecoder(r.Body).Decode(&gotPayload); err != nil {
			t.Errorf("decode body: %v", err)
		}
		w.WriteHeader(http.StatusNoContent)
	}))
	defer srv.Close()

	devs := []Device{
		{UUID: "uuid-1", Name: "FrontNVR", XAddr: "http://192.168.1.50/onvif/device_service"},
	}
	err := Report(context.Background(), srv.Client(), srv.URL, "tok-123", devs)
	if err != nil {
		t.Fatalf("Report returned error: %v", err)
	}
	if gotAuth != "Bearer tok-123" {
		t.Errorf("auth header = %q, want Bearer tok-123", gotAuth)
	}
	if len(gotPayload.Devices) != 1 || gotPayload.Devices[0].UUID != "uuid-1" {
		t.Errorf("payload = %+v", gotPayload)
	}
}

func TestReportEmptyListStillPosts(t *testing.T) {
	called := false
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		called = true
		var p reportPayload
		_ = json.NewDecoder(r.Body).Decode(&p)
		if p.Devices == nil || len(p.Devices) != 0 {
			t.Errorf("expected empty devices array, got %+v", p.Devices)
		}
		w.WriteHeader(http.StatusNoContent)
	}))
	defer srv.Close()

	if err := Report(context.Background(), srv.Client(), srv.URL, "tok", nil); err != nil {
		t.Fatalf("Report returned error: %v", err)
	}
	if !called {
		t.Error("backend was never called")
	}
}

func TestReportSurfacesHTTPError(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusUnauthorized)
	}))
	defer srv.Close()

	err := Report(context.Background(), srv.Client(), srv.URL, "bad-token", nil)
	if err == nil {
		t.Fatal("expected error on 401 response")
	}
}
