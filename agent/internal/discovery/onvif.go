package discovery

import (
	"context"
	"encoding/xml"
	"errors"
	"io"
	"net"
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
