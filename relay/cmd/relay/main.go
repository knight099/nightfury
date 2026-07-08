package main

import (
	"context"
	"errors"
	"log/slog"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"google.golang.org/grpc"

	tunnelpb "github.com/nightwatch/proto/gen/go/tunnelpb"
	"github.com/nightwatch/relay/internal/auth"
	"github.com/nightwatch/relay/internal/config"
	grpcserver "github.com/nightwatch/relay/internal/grpc_server"
	"github.com/nightwatch/relay/internal/republish"
	"github.com/nightwatch/relay/webrtcsignal"
)

func main() {
	cfg := config.Load()
	slog.Info("relay starting",
		"grpc", cfg.GRPCAddr, "rtsp", cfg.RTSPAddr, "webrtc", cfg.WebRTCSignalAddr,
	)

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	reg := republish.NewRegistry()

	verifier := auth.NewVerifier(cfg.BackendURL, cfg.WorkerKey, 5*time.Minute)

	// gRPC tunnel server
	grpcLis, err := net.Listen("tcp", cfg.GRPCAddr)
	if err != nil {
		slog.Error("grpc listen failed", "err", err)
		os.Exit(1)
	}
	gsrv := grpc.NewServer()
	tunnelSrv := &grpcserver.Server{
		Registry: reg,
		Auth:     auth.DeviceTokenAuthenticator{V: verifier},
		BufCap:   256,
	}
	tunnelpb.RegisterTunnelServer(gsrv, tunnelSrv)
	go func() {
		slog.Info("grpc serving", "addr", cfg.GRPCAddr)
		if err := gsrv.Serve(grpcLis); err != nil && !errors.Is(err, grpc.ErrServerStopped) {
			slog.Error("grpc serve exited", "err", err)
		}
	}()

	// RTSP republish server
	rtspSrv := republish.NewRTSPServer(reg, cfg.RTSPAddr)
	go func() {
		slog.Info("rtsp serving", "addr", cfg.RTSPAddr)
		if err := rtspSrv.Run(ctx); err != nil {
			slog.Error("rtsp serve exited", "err", err)
		}
	}()

	// WebRTC signaling HTTP server (agent push: /signal, browser view: /view)
	signalSrv := webrtcsignal.NewServerWithVerifier(verifier, reg)
	viewerSrv := webrtcsignal.NewViewerServer(cfg.StreamTokenSecret, reg)
	mux := http.NewServeMux()
	mux.Handle("/signal", signalSrv)
	mux.Handle("/view", viewerSrv)
	httpSrv := &http.Server{
		Addr:              cfg.WebRTCSignalAddr,
		Handler:           mux,
		ReadHeaderTimeout: 10 * time.Second,
	}
	go func() {
		slog.Info("webrtc signaling serving", "addr", cfg.WebRTCSignalAddr)
		if err := httpSrv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			slog.Error("webrtc signaling exited", "err", err)
		}
	}()

	<-ctx.Done()
	slog.Info("relay shutting down")

	shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	_ = httpSrv.Shutdown(shutdownCtx)
	gsrv.GracefulStop()
	_ = os.Stdout.Sync()
}
