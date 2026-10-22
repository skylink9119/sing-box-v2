#!/usr/bin/env bash
# Run inside a disposable Linux container, never on the workstation/VPS.
set -Eeuo pipefail
cd /workspace
source ./singbox-v2.sh
apt_install bash curl ca-certificates git python3 python3-yaml openssl shellcheck perl gnupg certbot python3-certbot-dns-cloudflare haproxy iproute2 procps
python3 scripts/build.py --check
for file in bootstrap.sh install.sh singbox-v2.sh src/*.sh scripts/ci.sh;do bash -n "$file";done
shellcheck src/quickstart.sh bootstrap.sh install.sh singbox-v2.sh scripts/ci.sh
bash singbox-v2.sh --self-check

# Official WARP CLI packaging may not support EOL Bullseye; protocol/install
# compatibility does not claim continued third-party repository support.
# shellcheck disable=SC1091 # Disposable container OS metadata.
source /etc/os-release
if [[ ${VERSION_ID:-} != 11 || ${ID:-} != debian ]];then
 curl -fsSL --proto '=https' --max-time 30 https://pkg.cloudflareclient.com/pubkey.gpg -o /tmp/warp-key
 gpg --batch --dearmor --output /usr/share/keyrings/skybyte-warp-ci.gpg /tmp/warp-key
 chmod 644 /usr/share/keyrings/skybyte-warp-ci.gpg
 printf 'deb [signed-by=/usr/share/keyrings/skybyte-warp-ci.gpg] https://pkg.cloudflareclient.com/ %s main\n' "$VERSION_CODENAME" > /etc/apt/sources.list.d/skybyte-warp-ci.list
 apt_install cloudflare-warp
 warp-cli mode --help
 warp-cli proxy port --help
 warp-cli registration new --help
fi
certbot certonly --help standalone
certbot certonly --help dns-cloudflare
certbot renew --help
mkdir -p work/tools
# Shared hosted-runner IPs can exhaust the anonymous GitHub API quota. The CI
# token is used only for API metadata, through a private curl config, not argv.
github_config=$(mktemp)
trap 'rm -f -- "$github_config"' EXIT
if [[ -n ${GH_TOKEN:-} ]];then
 printf 'header = "Authorization: Bearer %s"\n' "$GH_TOKEN" > "$github_config"
 curl(){
  local argument
  for argument in "$@";do
   if [[ $argument == https://api.github.com/* ]];then command curl -q -K "$github_config" "$@";return;fi
  done
  command curl "$@"
 }
fi
download_binary 1.14.3 "$PWD/work/tools/sing-box"
if [[ -n ${GH_TOKEN:-} ]];then unset -f curl;fi
rm -f -- "$github_config";trap - EXIT;unset GH_TOKEN
curl -fsSL --retry 2 https://github.com/MetaCubeX/mihomo/releases/download/v1.19.32/mihomo-linux-amd64-compatible-v1.19.32.gz -o work/tools/mihomo.gz
printf '%s\n' 'ba3ce607747a07f948fc35780e108a4a7c7f552a38b9bd4d115f313ebcb89c20  work/tools/mihomo.gz' | sha256sum -c -
gzip -d work/tools/mihomo.gz
chmod 755 work/tools/mihomo
SING_BOX_BIN="$PWD/work/tools/sing-box" MIHOMO_BIN="$PWD/work/tools/mihomo" python3 -m unittest discover -s tests -v
SING_BOX_BIN="$PWD/work/tools/sing-box" python3 scripts/benchmark_users.py --engine "$PWD/work/tools/sing-box" --counts 10,30,50 --output work/account-benchmark.json
chmod 755 work
chmod 644 work/account-benchmark.json
