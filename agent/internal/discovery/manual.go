package discovery

import (
	"fmt"
	"net/url"
)

// BuildManualRTSP constructs an RTSP URL based on a brand template.
//
// Supported brands: cpplus, hikvision, dahua, reolink, generic.
// `stream` is "main" or "sub". `channel` is 1-based.
func BuildManualRTSP(brand, host string, port int, user, pass string, channel int, stream string) (string, error) {
	subtype := 0
	if stream == "sub" {
		subtype = 1
	}
	userInfo := url.UserPassword(user, pass).String()
	switch brand {
	case "cpplus", "dahua":
		return fmt.Sprintf("rtsp://%s@%s:%d/cam/realmonitor?channel=%d&subtype=%d",
			userInfo, host, port, channel, subtype), nil
	case "hikvision":
		streamDigit := 1
		if stream == "sub" {
			streamDigit = 2
		}
		return fmt.Sprintf("rtsp://%s@%s:%d/Streaming/Channels/%d0%d",
			userInfo, host, port, channel, streamDigit), nil
	case "reolink":
		return fmt.Sprintf("rtsp://%s@%s:%d/h264Preview_%02d_%s",
			userInfo, host, port, channel, stream), nil
	case "generic":
		return fmt.Sprintf("rtsp://%s@%s:%d/", userInfo, host, port), nil
	default:
		return "", fmt.Errorf("unknown brand %q", brand)
	}
}
