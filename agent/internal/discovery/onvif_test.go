package discovery

import (
	"testing"

	"github.com/stretchr/testify/require"
)

func TestParseRTSPFromGetStreamURIResponse(t *testing.T) {
	xml := []byte(`<?xml version="1.0"?>
<env:Envelope xmlns:env="http://www.w3.org/2003/05/soap-envelope">
  <env:Body>
    <trt:GetStreamUriResponse xmlns:trt="http://www.onvif.org/ver10/media/wsdl">
      <trt:MediaUri>
        <tt:Uri xmlns:tt="http://www.onvif.org/ver10/schema">rtsp://192.168.1.108:554/Streaming/Channels/101</tt:Uri>
      </trt:MediaUri>
    </trt:GetStreamUriResponse>
  </env:Body>
</env:Envelope>`)
	uri, err := parseStreamURI(xml)
	require.NoError(t, err)
	require.Equal(t, "rtsp://192.168.1.108:554/Streaming/Channels/101", uri)
}

func TestParseStreamURI_NoURIReturnsError(t *testing.T) {
	_, err := parseStreamURI([]byte(`<x/>`))
	require.Error(t, err)
}
