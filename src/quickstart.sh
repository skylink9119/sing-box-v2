#!/usr/bin/env bash
(if ! command -v curl >/dev/null; then apt-get update && apt-get install -y curl ca-certificates; fi && script=$(curl -q -fsSL --max-time 60 https://raw.githubusercontent.com/skylink9119/sing-box-v2/main/bootstrap.sh) && bash -c "$script")
