package discovery

import (
	"bytes"
	"context"
	"crypto/rand"
	"crypto/sha1"
	"crypto/tls"
	"encoding/base64"
	"encoding/xml"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/google/uuid"
)

// Discovered describes an ONVIF NVR found on the LAN. (Legacy shape kept for
// existing callers; the onboarding flow now uses Device.)
type Discovered struct {
	XAddr      string
	Endpoint   string
	Name       string
	Make       string
	Model      string
	StreamURIs []string
}

// Device is the onboarding-flow shape returned by Discover for ONVIF
// devices that respond to a WS-Discovery probe.
type Device struct {
	UUID  string
	Name  string
	XAddr string
}

const probePayload = `<?xml version="1.0" encoding="UTF-8"?>
<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope"
            xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing"
            xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery">
  <e:Header>
    <w:MessageID>uuid:%s</w:MessageID>
    <w:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>
    <w:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action>
  </e:Header>
  <e:Body>
    <d:Probe><d:Types xmlns:dn="http://www.onvif.org/ver10/network/wsdl">dn:NetworkVideoTransmitter</d:Types></d:Probe>
  </e:Body>
</e:Envelope>`

type probeEnvelope struct {
	XMLName xml.Name `xml:"Envelope"`
	Body    struct {
		Matches struct {
			Match []struct {
				Scopes string `xml:"Scopes"`
				XAddrs string `xml:"XAddrs"`
				EPR    struct {
					Addr string `xml:"Address"`
				} `xml:"EndpointReference"`
			} `xml:"ProbeMatch"`
		} `xml:"ProbeMatches"`
	} `xml:"Body"`
}

// parseProbeMatches decodes a SOAP envelope containing zero or more
// ProbeMatch elements into Device records.
func parseProbeMatches(r io.Reader) ([]Device, error) {
	var env probeEnvelope
	if err := xml.NewDecoder(r).Decode(&env); err != nil {
		return nil, err
	}
	out := make([]Device, 0, len(env.Body.Matches.Match))
	for _, m := range env.Body.Matches.Match {
		fields := strings.Fields(m.XAddrs)
		xaddr := ""
		if len(fields) > 0 {
			xaddr = fields[0]
		}
		out = append(out, Device{
			UUID:  m.EPR.Addr,
			XAddr: xaddr,
			Name:  extractName(m.Scopes),
		})
	}
	return out, nil
}

func extractName(scopes string) string {
	for _, s := range strings.Fields(scopes) {
		if i := strings.Index(s, "/name/"); i >= 0 {
			return s[i+len("/name/"):]
		}
	}
	return "unknown"
}

// Discover sends a WS-Discovery probe to the IPv4 multicast group
// 239.255.255.250:3702 and returns deduped ProbeMatch responses received
// before timeout elapses.
func Discover(ctx context.Context, timeout time.Duration) ([]Device, error) {
	addr, err := net.ResolveUDPAddr("udp4", "239.255.255.250:3702")
	if err != nil {
		return nil, err
	}
	conn, err := net.ListenUDP("udp4", &net.UDPAddr{IP: net.IPv4zero, Port: 0})
	if err != nil {
		return nil, err
	}
	defer conn.Close()
	msgID := uuid.NewString()
	payload := []byte(strings.Replace(probePayload, "%s", msgID, 1))
	if _, err := conn.WriteToUDP(payload, addr); err != nil {
		return nil, err
	}
	deadline := time.Now().Add(timeout)
	if d, ok := ctx.Deadline(); ok && d.Before(deadline) {
		deadline = d
	}
	_ = conn.SetReadDeadline(deadline)
	buf := make([]byte, 32*1024)
	var devs []Device
	seen := map[string]struct{}{}
	for {
		n, _, rerr := conn.ReadFromUDP(buf)
		if rerr != nil {
			break
		}
		parsed, perr := parseProbeMatches(strings.NewReader(string(buf[:n])))
		if perr != nil {
			continue
		}
		for _, d := range parsed {
			if _, ok := seen[d.UUID]; ok {
				continue
			}
			seen[d.UUID] = struct{}{}
			devs = append(devs, d)
		}
	}
	return devs, nil
}

func parseStreamURI(body []byte) (string, error) {
	var env struct {
		Body struct {
			GetStreamUriResponse struct {
				MediaUri struct {
					Uri string `xml:"Uri"`
				} `xml:"MediaUri"`
			} `xml:"GetStreamUriResponse"`
		} `xml:"Body"`
	}
	if err := xml.Unmarshal(body, &env); err != nil {
		return "", err
	}
	uri := env.Body.GetStreamUriResponse.MediaUri.Uri
	if uri == "" {
		return "", errors.New("no Uri element found")
	}
	return uri, nil
}

// wsSecurityHeader builds a WS-Security UsernameToken header using
// PasswordDigest auth, as required by ONVIF's Media service.
func wsSecurityHeader(username, password string) (string, error) {
	nonceBytes := make([]byte, 16)
	if _, err := rand.Read(nonceBytes); err != nil {
		return "", err
	}
	nonce := base64.StdEncoding.EncodeToString(nonceBytes)
	created := time.Now().UTC().Format("2006-01-02T15:04:05.000Z")

	h := sha1.New()
	h.Write(nonceBytes)
	h.Write([]byte(created))
	h.Write([]byte(password))
	digest := base64.StdEncoding.EncodeToString(h.Sum(nil))

	return fmt.Sprintf(`<wsse:Security xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd" xmlns:wsu="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd">
  <wsse:UsernameToken>
    <wsse:Username>%s</wsse:Username>
    <wsse:Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest">%s</wsse:Password>
    <wsse:Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary">%s</wsse:Nonce>
    <wsu:Created>%s</wsu:Created>
  </wsse:UsernameToken>
</wsse:Security>`, username, digest, nonce, created), nil
}

func soapEnvelope(security, body string) string {
	return fmt.Sprintf(`<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">
  <s:Header>%s</s:Header>
  <s:Body>%s</s:Body>
</s:Envelope>`, security, body)
}

// SoapFaultError wraps a non-2xx ONVIF SOAP response. It carries the raw
// response body only in memory so FaultCode can parse it on demand;
// Error() itself does not include the body, so a bare log.Printf("%v", err)
// can never spill a full SOAP fault (or, in principle, anything echoed
// back from the device) into logs.
type SoapFaultError struct {
	Action     string
	StatusCode int
	Body       []byte
}

func (e *SoapFaultError) Error() string {
	return fmt.Sprintf("onvif %s: status %d", e.Action, e.StatusCode)
}

// FaultCode extracts the SOAP Fault Code/Value from a SoapFaultError's
// response body, for callers that must log an ONVIF failure without ever
// logging the full fault text (which could echo request data back). Returns
// "" if err is not a SoapFaultError or the body has no parseable fault
// code.
func FaultCode(err error) string {
	var soapErr *SoapFaultError
	if !errors.As(err, &soapErr) {
		return ""
	}
	var env struct {
		Body struct {
			Fault struct {
				Code struct {
					Value string `xml:"Value"`
				} `xml:"Code"`
			} `xml:"Fault"`
		} `xml:"Body"`
	}
	if xml.Unmarshal(soapErr.Body, &env) != nil {
		return ""
	}
	return env.Body.Fault.Code.Value
}

func postSOAP(ctx context.Context, client *http.Client, xaddr, action, security, body string) ([]byte, error) {
	req, err := http.NewRequestWithContext(
		ctx, http.MethodPost, xaddr, bytes.NewReader([]byte(soapEnvelope(security, body))),
	)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/soap+xml; charset=utf-8")
	req.Header.Set("SOAPAction", action)

	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}
	if resp.StatusCode >= 300 {
		return nil, &SoapFaultError{Action: action, StatusCode: resp.StatusCode, Body: respBody}
	}
	return respBody, nil
}

func parseProfileTokens(body []byte) ([]string, error) {
	var env struct {
		Body struct {
			GetProfilesResponse struct {
				Profiles []struct {
					Token string `xml:"token,attr"`
				} `xml:"Profiles"`
			} `xml:"GetProfilesResponse"`
		} `xml:"Body"`
	}
	if err := xml.Unmarshal(body, &env); err != nil {
		return nil, err
	}
	tokens := make([]string, 0, len(env.Body.GetProfilesResponse.Profiles))
	for _, p := range env.Body.GetProfilesResponse.Profiles {
		if p.Token != "" {
			tokens = append(tokens, p.Token)
		}
	}
	if len(tokens) == 0 {
		return nil, errors.New("no media profiles found")
	}
	return tokens, nil
}

const (
	mediaNS         = "http://www.onvif.org/ver10/media/wsdl"
	getProfilesAct  = mediaNS + "/GetProfiles"
	getStreamURIAct = mediaNS + "/GetStreamUri"
)

// ResolveStreamURI authenticates against the ONVIF device at xaddr (the
// device service URL from WS-Discovery), fetches its media profiles, and
// returns the RTSP stream URI for the first profile.
//
// This replaces guessing a generic rtsp://host:554/ URL — different
// brands/models use different ports and paths, and only the device itself
// knows the correct one.
func ResolveStreamURI(ctx context.Context, xaddr, username, password string) (string, error) {
	// LAN cameras commonly advertise https:// ONVIF endpoints with
	// self-signed or non-standards-compliant certs. We already trust this
	// device with admin credentials over the LAN, so skip verification
	// rather than failing discovery outright.
	client := &http.Client{
		Timeout: 10 * time.Second,
		Transport: &http.Transport{
			TLSClientConfig: &tls.Config{InsecureSkipVerify: true},
		},
	}

	security, err := wsSecurityHeader(username, password)
	if err != nil {
		return "", err
	}

	profilesBody := `<trt:GetProfiles xmlns:trt="` + mediaNS + `"/>`
	resp, err := postSOAP(ctx, client, xaddr, getProfilesAct, security, profilesBody)
	if err != nil {
		return "", fmt.Errorf("GetProfiles: %w", err)
	}
	tokens, err := parseProfileTokens(resp)
	if err != nil {
		return "", fmt.Errorf("GetProfiles: %w", err)
	}

	// Re-sign: nonces/timestamps must be fresh per request.
	security, err = wsSecurityHeader(username, password)
	if err != nil {
		return "", err
	}
	streamBody := fmt.Sprintf(
		`<trt:GetStreamUri xmlns:trt="%s" xmlns:tt="http://www.onvif.org/ver10/schema">
  <trt:StreamSetup>
    <tt:Stream>RTP-Unicast</tt:Stream>
    <tt:Transport><tt:Protocol>RTSP</tt:Protocol></tt:Transport>
  </trt:StreamSetup>
  <trt:ProfileToken>%s</trt:ProfileToken>
</trt:GetStreamUri>`, mediaNS, tokens[0],
	)
	resp, err = postSOAP(ctx, client, xaddr, getStreamURIAct, security, streamBody)
	if err != nil {
		return "", fmt.Errorf("GetStreamUri: %w", err)
	}
	streamURI, err := parseStreamURI(resp)
	if err != nil {
		return "", err
	}
	return withCredentials(streamURI, username, password)
}

// Channel is one ONVIF media profile enumerated from an NVR: enough to
// identify a camera channel for the onboarding UI without carrying a
// stream URI (and therefore without carrying credentials) back to the
// backend and, from there, to the browser.
type Channel struct {
	ProfileToken string
}

// ResolveAllStreamURIs authenticates against the ONVIF device at xaddr and
// enumerates every media profile it advertises (one per NVR channel),
// confirming each one actually resolves to a stream URI before including
// it. It shares wsSecurityHeader/postSOAP/parseProfileTokens/parseStreamURI
// with ResolveStreamURI rather than duplicating the SOAP plumbing; unlike
// ResolveStreamURI it deliberately discards the resolved URI (which would
// carry the NVR credentials) and returns only the profile token per
// channel.
//
// A per-profile GetStreamUri failure does NOT abort the whole call: it is
// common for a multi-channel NVR to have media profiles for channels with
// no camera attached, or a disabled substream. Such profiles are skipped
// (logged at profile-token + SOAP-fault-code granularity, never with the
// password) and every profile that DID resolve is still returned. Only a
// GetProfiles failure, or every single profile failing GetStreamUri, is
// reported as an error — a customer with a 16-channel NVR and one dead
// channel must still see the 15 working ones.
func ResolveAllStreamURIs(ctx context.Context, xaddr, username, password string) ([]Channel, error) {
	client := &http.Client{
		Timeout: 10 * time.Second,
		Transport: &http.Transport{
			TLSClientConfig: &tls.Config{InsecureSkipVerify: true},
		},
	}

	security, err := wsSecurityHeader(username, password)
	if err != nil {
		return nil, err
	}
	profilesBody := `<trt:GetProfiles xmlns:trt="` + mediaNS + `"/>`
	resp, err := postSOAP(ctx, client, xaddr, getProfilesAct, security, profilesBody)
	if err != nil {
		return nil, fmt.Errorf("GetProfiles: %w", err)
	}
	tokens, err := parseProfileTokens(resp)
	if err != nil {
		return nil, fmt.Errorf("GetProfiles: %w", err)
	}

	channels := make([]Channel, 0, len(tokens))
	for _, token := range tokens {
		// Re-sign per request: nonces/timestamps must be fresh.
		security, err = wsSecurityHeader(username, password)
		if err != nil {
			// Only a local nonce/random-read failure, not an ONVIF fault —
			// not worth continuing the loop over.
			return nil, err
		}
		streamBody := fmt.Sprintf(
			`<trt:GetStreamUri xmlns:trt="%s" xmlns:tt="http://www.onvif.org/ver10/schema">
  <trt:StreamSetup>
    <tt:Stream>RTP-Unicast</tt:Stream>
    <tt:Transport><tt:Protocol>RTSP</tt:Protocol></tt:Transport>
  </trt:StreamSetup>
  <trt:ProfileToken>%s</trt:ProfileToken>
</trt:GetStreamUri>`, mediaNS, token,
		)
		streamResp, serr := postSOAP(ctx, client, xaddr, getStreamURIAct, security, streamBody)
		if serr != nil {
			slog.Warn("nvr channel skipped: GetStreamUri failed",
				"profile_token", token, "fault_code", FaultCode(serr))
			continue
		}
		if _, perr := parseStreamURI(streamResp); perr != nil {
			slog.Warn("nvr channel skipped: no stream uri in response", "profile_token", token)
			continue
		}
		channels = append(channels, Channel{ProfileToken: token})
	}
	if len(channels) == 0 {
		return nil, errors.New("no profile resolved a stream uri")
	}
	return channels, nil
}

// withCredentials embeds the NVR username/password into the RTSP URL.
// ONVIF GetStreamUri responses normally omit credentials, but the RTSP
// server itself requires them for the DESCRIBE/SETUP handshake.
func withCredentials(rawURL, username, password string) (string, error) {
	u, err := url.Parse(rawURL)
	if err != nil {
		return "", fmt.Errorf("parse stream uri: %w", err)
	}
	u.User = url.UserPassword(username, password)
	return u.String(), nil
}
