package store

import (
	"encoding/json"
	"errors"
	"io/fs"
	"os"
)

// Token is the long-lived device credential persisted on the agent host
// after successful pairing with the backend.
type Token struct {
	DeviceToken string `json:"device_token"`
	RelayURL    string `json:"relay_url"`
	OrgID       string `json:"org_id"`
	AgentID     string `json:"agent_id"`
}

// Store reads and writes a Token to a file on disk.
type Store struct{ path string }

// New creates a Store backed by the given file path.
func New(path string) *Store { return &Store{path: path} }

// Save writes the token as JSON with 0600 permissions.
func (s *Store) Save(t Token) error {
	b, err := json.Marshal(t)
	if err != nil {
		return err
	}
	return os.WriteFile(s.path, b, 0600)
}

// Load reads and decodes the token from disk. Returns an error if the
// file is missing.
func (s *Store) Load() (Token, error) {
	b, err := os.ReadFile(s.path)
	if err != nil {
		if errors.Is(err, fs.ErrNotExist) {
			return Token{}, errors.New("not paired yet")
		}
		return Token{}, err
	}
	var t Token
	return t, json.Unmarshal(b, &t)
}

// Exists reports whether a token file is present on disk.
func (s *Store) Exists() bool {
	_, err := os.Stat(s.path)
	return err == nil
}
