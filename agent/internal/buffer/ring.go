package buffer

import "sync"

type Ring[T any] struct {
	mu      sync.Mutex
	data    []T
	head    int
	size    int
	cap     int
	dropped int
}

func New[T any](capacity int) *Ring[T] {
	if capacity <= 0 {
		capacity = 1
	}
	return &Ring[T]{data: make([]T, capacity), cap: capacity}
}

func (r *Ring[T]) Push(v T) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.size == r.cap {
		r.head = (r.head + 1) % r.cap
		r.size--
		r.dropped++
	}
	tail := (r.head + r.size) % r.cap
	r.data[tail] = v
	r.size++
}

func (r *Ring[T]) Pop() (T, bool) {
	r.mu.Lock()
	defer r.mu.Unlock()
	var zero T
	if r.size == 0 {
		return zero, false
	}
	v := r.data[r.head]
	r.data[r.head] = zero
	r.head = (r.head + 1) % r.cap
	r.size--
	return v, true
}

func (r *Ring[T]) Len() int          { r.mu.Lock(); defer r.mu.Unlock(); return r.size }
func (r *Ring[T]) Cap() int          { return r.cap }
func (r *Ring[T]) DroppedCount() int { r.mu.Lock(); defer r.mu.Unlock(); return r.dropped }
