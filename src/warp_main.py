"""Owned WARP/landing routing transactions; client-facing node credentials stay intact."""
import base64
import configparser
import copy
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import hashlib
import socket
import ssl
import time
import urllib.parse
import uuid

OWNER='SKYBYTE WARP routing v1'
MEDIA=['netflix.com','netflix.net','nflxext.com','nflximg.com','nflximg.net','nflxso.net','nflxvideo.net',
       'disneyplus.com','disney-plus.net','dssott.com','bamgrid.com','youtube.com','youtu.be','googlevideo.com','ytimg.com','youtubei.googleapis.com',
       'primevideo.com','amazonvideo.com','aiv-cdn.net','aiv-delivery.net','tiktok.com','tiktokv.com','tiktokcdn.com','tiktokcdn-us.com','byteoversea.com','ibytedtos.com']
AI=['openai.com','chatgpt.com','oaistatic.com','oaiusercontent.com','anthropic.com','claude.ai','claude.com',
    'gemini.google.com','aistudio.google.com','generativelanguage.googleapis.com']
PROFILES={'netflix':MEDIA[:7],'disney':MEDIA[7:11],'chatgpt':AI[:4],'gemini':AI[7:]}
RULE_VERSION='2026.10.23'
FIELDS=('route','outbounds')
RELAY_OWNER='SKYBYTE relay profile v1'

# @include warp_relay.py

# @include warp_routing.py

# @include warp_gateway.py

# @include warp_cli.py
