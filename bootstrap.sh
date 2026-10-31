#!/usr/bin/env bash
(
 set -Eeuo pipefail
 if [[ $(id -u) != 0 ]];then printf 'Please run as root / 请以 root 账户运行\n' >&2;exit 1;fi
 os_id=$(awk -F= '$1=="ID" {gsub(/"/,"",$2);print $2}' "${OS_RELEASE:-/etc/os-release}")
 case $os_id in ubuntu|debian) :;; *) printf 'Ubuntu/Debian only / 仅支持 Ubuntu/Debian\n' >&2;exit 1;; esac
 if ! command -v curl >/dev/null 2>&1;then
  printf 'curl not found; installing curl and CA certificates / 未安装 curl，正在安装 curl 与 CA 证书……\n'
  if ! apt-get -o APT::Update::Error-Mode=any -o Acquire::Retries=2 --allow-releaseinfo-change-suite update;then
   printf 'APT refresh failed; download stopped / APT 索引更新失败，已停止下载，请先修复软件源或网络\n' >&2
   exit 1
  fi
  if ! DEBIAN_FRONTEND=noninteractive apt-get install -y curl ca-certificates;then
   printf 'curl installation failed; download stopped / curl 安装失败，已停止下载\n' >&2
   exit 1
  fi
  if ! command -v curl >/dev/null 2>&1;then printf 'curl is still unavailable / 安装后仍找不到 curl，请检查 PATH 或软件包状态\n' >&2;exit 1;fi
 fi
 installer=$(mktemp "${TMPDIR:-/tmp}/skybyte-install.XXXXXX")
 trap 'rm -f -- "$installer"' EXIT
 curl -q -fsSL --proto '=https' --proto-redir '=https' --retry 2 --connect-timeout 10 --max-time 120 https://github.com/skylink9119/sing-box-v2/releases/download/v2.8.21/install.sh -o "$installer"
 if [[ -s $installer ]] && head -n 1 "$installer" | grep -Fxq '#!/usr/bin/env bash' && bash -n "$installer";then :;else
  printf 'Invalid installer download / 安装脚本为空或格式错误，已停止执行\n' >&2;exit 1
 fi
 bash "$installer"
)
