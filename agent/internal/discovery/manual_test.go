package discovery

import (
	"testing"

	"github.com/stretchr/testify/require"
)

func TestBuildManualRTSP_CPPlus(t *testing.T) {
	got, err := BuildManualRTSP("cpplus", "192.168.1.108", 554, "admin", "p@ss", 1, "main")
	require.NoError(t, err)
	require.Equal(t, "rtsp://admin:p%40ss@192.168.1.108:554/cam/realmonitor?channel=1&subtype=0", got)
}

func TestBuildManualRTSP_Hikvision(t *testing.T) {
	got, err := BuildManualRTSP("hikvision", "10.0.0.5", 554, "admin", "x", 2, "sub")
	require.NoError(t, err)
	require.Equal(t, "rtsp://admin:x@10.0.0.5:554/Streaming/Channels/202", got)
}

func TestBuildManualRTSP_Dahua(t *testing.T) {
	got, err := BuildManualRTSP("dahua", "10.0.0.5", 554, "admin", "x", 1, "main")
	require.NoError(t, err)
	require.Equal(t, "rtsp://admin:x@10.0.0.5:554/cam/realmonitor?channel=1&subtype=0", got)
}

func TestBuildManualRTSP_UnknownBrand(t *testing.T) {
	_, err := BuildManualRTSP("unknown-brand", "1.2.3.4", 554, "u", "p", 1, "main")
	require.Error(t, err)
}
