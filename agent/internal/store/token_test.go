package store

import (
	"os"
	"path/filepath"
	"testing"
)

func TestSaveLoad(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "token.json")
	s := New(path)
	if err := s.Save(Token{DeviceToken: "abc", RelayURL: "grpcs://r", OrgID: "o", AgentID: "a"}); err != nil {
		t.Fatal(err)
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0600 {
		t.Fatalf("expected 0600, got %v", info.Mode().Perm())
	}
	tok, err := s.Load()
	if err != nil {
		t.Fatal(err)
	}
	if tok.DeviceToken != "abc" {
		t.Fatal("wrong token")
	}
	if !s.Exists() {
		t.Fatal("expected Exists() to be true after Save")
	}
}

func TestLoadMissing(t *testing.T) {
	s := New(filepath.Join(t.TempDir(), "missing.json"))
	if _, err := s.Load(); err == nil {
		t.Fatal("expected error")
	}
	if s.Exists() {
		t.Fatal("expected Exists() to be false for missing file")
	}
}
