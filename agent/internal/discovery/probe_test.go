package discovery

import (
	"strings"
	"testing"
)

const sampleProbeMatch = `<?xml version="1.0" encoding="UTF-8"?>
<env:Envelope xmlns:env="http://www.w3.org/2003/05/soap-envelope"
              xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing"
              xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery">
  <env:Body><d:ProbeMatches><d:ProbeMatch>
    <wsa:EndpointReference><wsa:Address>urn:uuid:cam-1</wsa:Address></wsa:EndpointReference>
    <d:Types>dn:NetworkVideoTransmitter</d:Types>
    <d:Scopes>onvif://www.onvif.org/name/CP-PLUS</d:Scopes>
    <d:XAddrs>http://192.168.1.50:80/onvif/device_service</d:XAddrs>
  </d:ProbeMatch></d:ProbeMatches></env:Body>
</env:Envelope>`

func TestParseProbeMatch(t *testing.T) {
	devs, err := parseProbeMatches(strings.NewReader(sampleProbeMatch))
	if err != nil {
		t.Fatal(err)
	}
	if len(devs) != 1 {
		t.Fatalf("got %d devices", len(devs))
	}
	if devs[0].XAddr != "http://192.168.1.50:80/onvif/device_service" {
		t.Fatalf("wrong xaddr: %s", devs[0].XAddr)
	}
	if devs[0].Name != "CP-PLUS" {
		t.Fatalf("wrong name: %s", devs[0].Name)
	}
	if devs[0].UUID != "urn:uuid:cam-1" {
		t.Fatalf("wrong uuid: %s", devs[0].UUID)
	}
}
