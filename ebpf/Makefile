CLANG ?= clang
BPFTOOL ?= bpftool
UNAME_M := $(shell uname -m)
ARCH ?= $(if $(filter aarch64 arm64,$(UNAME_M)),arm64,x86)
BPF_CFLAGS := -g -O2 -target bpf -D__TARGET_ARCH_$(ARCH) -Wall -Werror

.PHONY: all clean verify

all: tcp_metrics.bpf.o

tcp_metrics.bpf.o: tcp_metrics.bpf.c tcp_metrics.h
	$(CLANG) $(BPF_CFLAGS) -I/usr/include/$(shell uname -m)-linux-gnu -c $< -o $@

verify: tcp_metrics.bpf.o
	$(BPFTOOL) gen skeleton $< > /tmp/tcp_metrics.skel.h
	test -s /tmp/tcp_metrics.skel.h

clean:
	rm -f tcp_metrics.bpf.o /tmp/tcp_metrics.skel.h
