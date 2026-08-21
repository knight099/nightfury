module github.com/nightwatch/agent

go 1.26.3

replace github.com/nightwatch/proto/gen/go/tunnelpb => ../proto/gen/go/tunnelpb

replace github.com/nightwatch/relay => ../relay

require (
	github.com/bluenviron/gortsplib/v5 v5.5.3
	github.com/google/uuid v1.6.0
	github.com/gorilla/websocket v1.5.3
	github.com/nightwatch/proto/gen/go/tunnelpb v0.0.0-00010101000000-000000000000
	github.com/nightwatch/relay v0.0.0-00010101000000-000000000000
	github.com/pion/rtp v1.10.2
	github.com/pion/webrtc/v4 v4.2.13
	github.com/skip2/go-qrcode v0.0.0-20200617195104-da1b6568686e
	github.com/stretchr/testify v1.11.1
	google.golang.org/grpc v1.81.1
)

require (
	github.com/bluenviron/mediacommon/v2 v2.8.3 // indirect
	github.com/davecgh/go-spew v1.1.1 // indirect
	github.com/pion/datachannel v1.6.0 // indirect
	github.com/pion/dtls/v3 v3.1.2 // indirect
	github.com/pion/ice/v4 v4.2.5 // indirect
	github.com/pion/interceptor v0.1.45 // indirect
	github.com/pion/logging v0.2.4 // indirect
	github.com/pion/mdns/v2 v2.1.0 // indirect
	github.com/pion/randutil v0.1.0 // indirect
	github.com/pion/rtcp v1.2.16 // indirect
	github.com/pion/sctp v1.10.0 // indirect
	github.com/pion/sdp/v3 v3.0.18 // indirect
	github.com/pion/srtp/v3 v3.0.10 // indirect
	github.com/pion/stun/v3 v3.1.2 // indirect
	github.com/pion/transport/v4 v4.0.1 // indirect
	github.com/pion/turn/v5 v5.0.4 // indirect
	github.com/pmezard/go-difflib v1.0.0 // indirect
	github.com/wlynxg/anet v0.0.5 // indirect
	golang.org/x/crypto v0.51.0 // indirect
	golang.org/x/net v0.54.0 // indirect
	golang.org/x/sys v0.44.0 // indirect
	golang.org/x/text v0.37.0 // indirect
	golang.org/x/time v0.14.0 // indirect
	google.golang.org/genproto/googleapis/rpc v0.0.0-20260226221140-a57be14db171 // indirect
	google.golang.org/protobuf v1.36.11 // indirect
	gopkg.in/yaml.v3 v3.0.1 // indirect
)
