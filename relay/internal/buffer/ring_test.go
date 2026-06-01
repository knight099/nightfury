package buffer

import (
	"testing"

	"github.com/stretchr/testify/require"
)

func TestRing_PushPop_BelowCapacity(t *testing.T) {
	r := New[int](4)
	r.Push(1)
	r.Push(2)
	v, ok := r.Pop()
	require.True(t, ok)
	require.Equal(t, 1, v)
	v, ok = r.Pop()
	require.True(t, ok)
	require.Equal(t, 2, v)
	_, ok = r.Pop()
	require.False(t, ok)
}

func TestRing_DropsOldestWhenFull(t *testing.T) {
	r := New[int](3)
	r.Push(1)
	r.Push(2)
	r.Push(3)
	r.Push(4) // should drop 1
	require.Equal(t, 1, r.DroppedCount())
	v, _ := r.Pop()
	require.Equal(t, 2, v)
}

func TestRing_LenAndCap(t *testing.T) {
	r := New[int](2)
	require.Equal(t, 0, r.Len())
	r.Push(1)
	require.Equal(t, 1, r.Len())
	require.Equal(t, 2, r.Cap())
}
