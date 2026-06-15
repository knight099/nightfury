package discovery

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"time"
)

// reportDevice mirrors the backend's DiscoveredDevice schema.
type reportDevice struct {
	UUID  string `json:"uuid"`
	Name  string `json:"name"`
	XAddr string `json:"xaddr"`
}

type reportPayload struct {
	Devices []reportDevice `json:"devices"`
}

// Report uploads discovery results to the backend so the dashboard's
// onboarding wizard can list cameras found on this LAN.
func Report(ctx context.Context, client *http.Client, backendURL, deviceToken string, devs []Device) error {
	payload := reportPayload{Devices: make([]reportDevice, 0, len(devs))}
	for _, d := range devs {
		payload.Devices = append(payload.Devices, reportDevice{
			UUID: d.UUID, Name: d.Name, XAddr: d.XAddr,
		})
	}
	body, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	req, err := http.NewRequestWithContext(
		ctx, http.MethodPost, backendURL+"/api/agents/me/discovered", bytes.NewReader(body),
	)
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+deviceToken)

	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		return fmt.Errorf("discovery report rejected: %s", resp.Status)
	}
	return nil
}

// RunReporter discovers ONVIF devices on the LAN and reports them to the
// backend, repeating every interval until ctx is cancelled. Errors are
// logged and retried on the next tick — discovery is best-effort and must
// never take the streaming pipeline down with it.
func RunReporter(ctx context.Context, backendURL, deviceToken string, interval time.Duration) {
	client := &http.Client{Timeout: 15 * time.Second}
	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	for {
		devs, err := Discover(ctx, 5*time.Second)
		if err != nil {
			slog.Warn("onvif discovery failed", "err", err)
		} else {
			slog.Info("onvif discovery complete", "devices", len(devs))
			if err := Report(ctx, client, backendURL, deviceToken, devs); err != nil {
				slog.Warn("discovery report failed", "err", err)
			}
		}

		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
	}
}

// resolveJob mirrors the backend's ResolveJob schema.
type resolveJob struct {
	CameraID string `json:"camera_id"`
	XAddr    string `json:"xaddr"`
	User     string `json:"user"`
	Password string `json:"pass"`
}

type resolveJobsResponse struct {
	Jobs []resolveJob `json:"jobs"`
}

type resolveResultPayload struct {
	RTSPURL string `json:"rtsp_url,omitempty"`
	Error   string `json:"error,omitempty"`
}

// fetchResolveJobs drains the agent's pending ONVIF GetStreamUri jobs.
func fetchResolveJobs(ctx context.Context, client *http.Client, backendURL, deviceToken string) ([]resolveJob, error) {
	req, err := http.NewRequestWithContext(
		ctx, http.MethodGet, backendURL+"/api/agents/me/resolve-jobs", nil,
	)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", "Bearer "+deviceToken)

	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		return nil, fmt.Errorf("fetch resolve jobs: %s", resp.Status)
	}
	var out resolveJobsResponse
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	return out.Jobs, nil
}

// postResolveResult reports the RTSP URL (or error) resolved for a camera.
func postResolveResult(ctx context.Context, client *http.Client, backendURL, deviceToken, cameraID string, result resolveResultPayload) error {
	body, err := json.Marshal(result)
	if err != nil {
		return err
	}
	req, err := http.NewRequestWithContext(
		ctx, http.MethodPost, backendURL+"/api/agents/me/resolve-jobs/"+cameraID, bytes.NewReader(body),
	)
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+deviceToken)

	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		return fmt.Errorf("post resolve result: %s", resp.Status)
	}
	return nil
}

// RunResolver polls for pending ONVIF GetStreamUri jobs and resolves each by
// calling the discovered device directly with the NVR credentials the user
// supplied during onboarding. Runs until ctx is cancelled.
func RunResolver(ctx context.Context, backendURL, deviceToken string, interval time.Duration) {
	client := &http.Client{Timeout: 15 * time.Second}
	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	for {
		jobs, err := fetchResolveJobs(ctx, client, backendURL, deviceToken)
		if err != nil {
			slog.Warn("fetch resolve jobs failed", "err", err)
		}
		for _, job := range jobs {
			rtspURL, rerr := ResolveStreamURI(ctx, job.XAddr, job.User, job.Password)
			result := resolveResultPayload{RTSPURL: rtspURL}
			if rerr != nil {
				slog.Warn("resolve stream uri failed", "camera_id", job.CameraID, "err", rerr)
				result = resolveResultPayload{Error: rerr.Error()}
			} else {
				slog.Info("resolved stream uri", "camera_id", job.CameraID, "rtsp_url", rtspURL)
			}
			if err := postResolveResult(ctx, client, backendURL, deviceToken, job.CameraID, result); err != nil {
				slog.Warn("post resolve result failed", "camera_id", job.CameraID, "err", err)
			}
		}

		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
	}
}
