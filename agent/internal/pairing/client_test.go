package pairing

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestPairSuccess(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var body map[string]string
		_ = json.NewDecoder(r.Body).Decode(&body)
		if body["code"] != "123456" {
			t.Fatalf("got code %q", body["code"])
		}
		_, _ = w.Write([]byte(`{"device_token":"t","relay_url":"grpcs://r","org_id":"o","agent_id":"a"}`))
	}))
	defer srv.Close()
	c := NewClient(srv.URL)
	out, err := c.Pair(context.Background(), Request{Code: "123456", MachineID: "m12345678", Pubkey: "pubkey1234567890", Version: "0.1.0"})
	if err != nil {
		t.Fatal(err)
	}
	if out.DeviceToken != "t" {
		t.Fatal("wrong token")
	}
}

func TestPair400(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, `{"detail":"pairing failed: expired"}`, 400)
	}))
	defer srv.Close()
	c := NewClient(srv.URL)
	if _, err := c.Pair(context.Background(), Request{Code: "000000", MachineID: "m12345678", Pubkey: "pubkey1234567890"}); err == nil {
		t.Fatal("expected error")
	}
}
