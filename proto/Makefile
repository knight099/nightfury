PROTO_DIR := .
OUT_GO    := gen/go/tunnelpb

.PHONY: gen clean
gen:
	mkdir -p $(OUT_GO)
	protoc --go_out=$(OUT_GO) --go_opt=paths=source_relative \
	       --go-grpc_out=$(OUT_GO) --go-grpc_opt=paths=source_relative \
	       $(PROTO_DIR)/tunnel.proto

clean:
	rm -rf $(OUT_GO)
