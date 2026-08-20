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

// postJSON marshals payload, POSTs it to backendURL+path with the device
// token, and treats any non-2xx response as an error. Shared by every
// agent-authenticated push in this file.
func postJSON(ctx context.Context, client *http.Client, backendURL, deviceToken, path string, payload any) error {
	body, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	req, err := http.NewRequestWithContext(
		ctx, http.MethodPost, backendURL+path, bytes.NewReader(body),
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
		return fmt.Errorf("POST %s rejected: %s", path, resp.Status)
	}
	return nil
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
	return postJSON(ctx, client, backendURL, deviceToken, "/api/agents/me/discovered", payload)
}

// reportChannel mirrors the backend's DiscoveredChannel schema.
//
// Deliberately carries no stream URI: a resolved ONVIF stream URI embeds
// the NVR username/password (see withCredentials), and this struct is
// marshalled into a request that the backend later re-serves, verbatim, to
// the browser via GET /{agent_id}/channels. Only the profile token — an
// opaque channel identifier — crosses that boundary.
type reportChannel struct {
	ProfileToken string `json:"profile_token"`
}

// channelsPayload mirrors the backend's ChannelsPushRequest schema.
type channelsPayload struct {
	XAddr    string          `json:"xaddr"`
	Channels []reportChannel `json:"channels"`
}

// ReportChannels uploads the channels enumerated from a single NVR (found
// via ResolveAllStreamURIs) to their own endpoint/key
// (POST /api/agents/me/channels), NOT the WS-Discovery snapshot endpoint.
// The discovery snapshot at /me/discovered is whole-snapshot-replaced by
// both the periodic sweep (RunReporter, ~every 60s) and scan_now, so a
// channel list posted through it would be silently wiped by the next
// sweep; posting there also required synthesizing a fake "device" entry
// for the NVR, which this endpoint has no need to do since it isn't a
// device list.
func ReportChannels(ctx context.Context, client *http.Client, backendURL, deviceToken, xaddr string, channels []Channel) error {
	rc := make([]reportChannel, 0, len(channels))
	for _, c := range channels {
		rc = append(rc, reportChannel{ProfileToken: c.ProfileToken})
	}
	payload := channelsPayload{XAddr: xaddr, Channels: rc}
	return postJSON(ctx, client, backendURL, deviceToken, "/api/agents/me/channels", payload)
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

// nvrCredentials mirrors the backend's NvrCredentialsResponse schema.
type nvrCredentials struct {
	XAddr    string `json:"xaddr"`
	Username string `json:"username"`
	Password string `json:"password"`
}

// fetchNvrCredentials fetches (and, server-side, deletes) the credentials
// staged by POST /{agent_id}/nvr-channels. A 404 means nothing is pending
// — not an error, just nothing to do — and is reported as (nil, nil).
func fetchNvrCredentials(ctx context.Context, client *http.Client, backendURL, deviceToken string) (*nvrCredentials, error) {
	req, err := http.NewRequestWithContext(
		ctx, http.MethodGet, backendURL+"/api/agents/me/nvr-credentials", nil,
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
	if resp.StatusCode == http.StatusNotFound {
		return nil, nil
	}
	if resp.StatusCode >= 300 {
		return nil, fmt.Errorf("fetch nvr credentials: %s", resp.Status)
	}
	var out nvrCredentials
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	return &out, nil
}

// ResolveChannels drains the NVR credentials staged for this agent (if
// any), enumerates the NVR's ONVIF media profiles, and reports the channel
// list back to the backend. Called on the "resolve_channels" control
// message.
//
// The credentials are read once, held only in local variables for the
// duration of this call, and never logged — not even on failure. An ONVIF
// failure logs only the xaddr and the SOAP fault code (via
// discovery.FaultCode), never the username, the password, or a raw
// response body that might echo request data back.
func ResolveChannels(ctx context.Context, backendURL, deviceToken string) {
	client := &http.Client{Timeout: 15 * time.Second}

	creds, err := fetchNvrCredentials(ctx, client, backendURL, deviceToken)
	if err != nil {
		slog.Warn("fetch nvr credentials failed", "err", err)
		return
	}
	if creds == nil {
		// Nothing pending — the command arrived after the credentials
		// already expired, or were already consumed by a prior delivery.
		return
	}

	channels, err := ResolveAllStreamURIs(ctx, creds.XAddr, creds.Username, creds.Password)
	if err != nil {
		slog.Warn("resolve nvr channels failed", "xaddr", creds.XAddr, "fault_code", FaultCode(err))
		return
	}
	slog.Info("resolved nvr channels", "xaddr", creds.XAddr, "channels", len(channels))

	if err := ReportChannels(ctx, client, backendURL, deviceToken, creds.XAddr, channels); err != nil {
		slog.Warn("report nvr channels failed", "xaddr", creds.XAddr, "err", err)
	}
}
