package republish

import (
	"errors"
	"sync"

	"github.com/nightwatch/agent/internal/buffer"
)

type Publisher struct {
	CameraID string
	Frames   *buffer.Ring[[]byte]
}

func NewPublisher(cameraID string, bufCap int) *Publisher {
	return &Publisher{
		CameraID: cameraID,
		Frames:   buffer.New[[]byte](bufCap),
	}
}

type Registry struct {
	mu  sync.RWMutex
	pub map[string]*Publisher
}

func NewRegistry() *Registry { return &Registry{pub: make(map[string]*Publisher)} }

func (r *Registry) Register(id string, p *Publisher) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.pub[id] = p
}

func (r *Registry) RegisterErr(id string, p *Publisher) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	if _, exists := r.pub[id]; exists {
		return errors.New("camera already registered")
	}
	r.pub[id] = p
	return nil
}

func (r *Registry) Unregister(id string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	delete(r.pub, id)
}

func (r *Registry) Get(id string) (*Publisher, bool) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	p, ok := r.pub[id]
	return p, ok
}
