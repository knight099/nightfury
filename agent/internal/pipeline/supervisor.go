// Package pipeline supervises the Python detection pipeline (agent/pipeline/)
// as a restarting child process. It is a process supervisor, distinct from
// the camera-transport orchestration in internal/supervisor.
package pipeline

import (
	"context"
	"log"
	"os/exec"
	"sync"
	"time"
)

// Health reports the current run state of the supervised pipeline process.
type Health struct {
	Status      string
	LastRestart time.Time
}

// Supervisor runs the Python detection pipeline as a child process,
// restarting it on crash/exit with exponential backoff capped at 30s.
type Supervisor struct {
	pythonPath  string
	pipelineDir string
	env         []string

	mu     sync.Mutex
	health Health
}

// NewSupervisor constructs a Supervisor that will run pythonPath main.py
// with cwd pipelineDir and the given environment (which should include a
// base environment such as os.Environ() plus any pipeline-specific vars).
func NewSupervisor(pythonPath, pipelineDir string, env []string) *Supervisor {
	return &Supervisor{
		pythonPath:  pythonPath,
		pipelineDir: pipelineDir,
		env:         env,
		health:      Health{Status: "starting"},
	}
}

// Health returns the supervisor's current view of the pipeline process's
// health. Safe for concurrent use.
func (s *Supervisor) Health() Health {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.health
}

func (s *Supervisor) setHealth(status string) {
	s.mu.Lock()
	s.health = Health{Status: status, LastRestart: time.Now()}
	s.mu.Unlock()
}

// Run blocks, spawning the pipeline process and restarting it on exit until
// ctx is cancelled. It respects ctx cancellation both between runs and
// during the backoff wait.
func (s *Supervisor) Run(ctx context.Context) error {
	backoff := time.Second
	for {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		cmd := exec.CommandContext(ctx, s.pythonPath, "main.py")
		cmd.Dir = s.pipelineDir
		cmd.Env = s.env
		cmd.Stdout = log.Writer()
		cmd.Stderr = log.Writer()
		s.setHealth("running")
		err := cmd.Run()
		if ctx.Err() != nil {
			return ctx.Err()
		}
		s.setHealth("restarting")
		log.Printf("pipeline sidecar exited (%v), restarting in %s", err, backoff)
		select {
		case <-time.After(backoff):
		case <-ctx.Done():
			return ctx.Err()
		}
		if backoff < 30*time.Second {
			backoff *= 2
			if backoff > 30*time.Second {
				backoff = 30 * time.Second
			}
		}
	}
}
