#!/usr/bin/env python3
"""
local_ssh_test.py
=================
NetBrain AI — Standalone SSH connectivity test
-----------------------------------------------
Run this directly from your Mac terminal to verify SSH works
BEFORE using the web app. This is the fastest way to debug
credential or cipher issues.

Usage:
    cd ~/Desktop/network-intelligence-platform
    python3 local_ssh_test.py

Or with custom credentials:
    python3 local_ssh_test.py --ip 192.168.96.128 --user admin --pass admin
"""

import sys
import os
import argparse
import socket
import subprocess
import time

# ── Load .env first ──────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
    print("✅ .env loaded")
except ImportError:
    print("⚠️  python-dotenv not installed — using env vars only")

# ── CLI args ─────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description="NetBrain AI — SSH Test")
parser.add_argument("--ip",     default=os.environ.get("GNS3_ROUTER_IP", "192.168.96.128"))
parser.add_argument("--user",   default=os.environ.get("GNS3_SSH_USER",  "admin"))
parser.add_argument("--pass",   dest="password",
                                default=os.environ.get("GNS3_SSH_PASS",  "admin"))
parser.add_argument("--secret", default=os.environ.get("GNS3_SSH_SECRET", ""))
parser.add_argument("--port",   type=int, default=22)
parser.add_argument("--type",   default=os.environ.get("GNS3_DEVICE_TYPE", "cisco_ios"))
parser.add_argument("--cmd",    default="show ip interface brief",
                                help="Command to run after login")
args = parser.parse_args()

print()
print("=" * 60)
print("  NetBrain AI — SSH Connectivity Test")
print("=" * 60)
print(f"  Target  : {args.user}@{args.ip}:{args.port}")
print(f"  Type    : {args.type}")
print(f"  Command : {args.cmd}")
print("=" * 60)
print()

# ── Step 1: Ping ─────────────────────────────────────────────────────────────
print("STEP 1: Ping test...")
try:
    t0 = time.perf_counter()
    rc = subprocess.call(
        ["ping", "-c", "1", "-W", "2000", args.ip],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    rtt = (time.perf_counter() - t0) * 1000
    if rc == 0:
        print(f"  ✅ Ping OK — {rtt:.0f} ms")
    else:
        print(f"  ❌ Ping FAILED — device not reachable")
        sys.exit(1)
except Exception as e:
    print(f"  ⚠️  Ping error: {e}")

# ── Step 2: TCP port ─────────────────────────────────────────────────────────
print(f"STEP 2: TCP port {args.port}...")
try:
    with socket.create_connection((args.ip, args.port), timeout=5):
        print(f"  ✅ Port {args.port} open")
except Exception as e:
    print(f"  ❌ Port {args.port} CLOSED — {e}")
    sys.exit(1)

# ── Step 3: Netmiko login ────────────────────────────────────────────────────
print(f"STEP 3: SSH login as '{args.user}'...")
try:
    from netmiko import ConnectHandler
    print(f"  → Connecting to {args.type} at {args.ip}:{args.port}...")
    conn = ConnectHandler(
        device_type=args.type,
        host=args.ip,
        port=args.port,
        username=args.user,
        password=args.password,
        secret=args.secret if args.secret else args.password,
        timeout=30,
        auth_timeout=30,
        conn_timeout=15,
        fast_cli=False,
        global_delay_factor=2,
    )
    prompt = conn.find_prompt()
    print(f"  ✅ LOGIN SUCCESS! Prompt: {prompt}")
except ImportError:
    print("  ❌ netmiko not installed — run: pip install netmiko")
    sys.exit(1)
except Exception as e:
    print(f"  ❌ LOGIN FAILED: {e}")
    print()
    print("  Troubleshooting:")
    print(f"    - Check username/password match router: username {args.user} privilege 15 password 0 {args.password}")
    print(f"    - Your router config shows: username admin privilege 15 password 0 admin")
    print(f"    - Make sure 'transport input ssh' or 'transport input all' on VTY lines")
    print(f"    - Try: ssh -o KexAlgorithms=diffie-hellman-group1-sha1 {args.user}@{args.ip}")
    sys.exit(1)

# ── Step 5: Run command ───────────────────────────────────────────────────────
print(f"STEP 5: Running '{args.cmd}'...")
try:
    output = conn.send_command(args.cmd, read_timeout=15)
    print(f"  ✅ Command output:")
    print()
    for line in output.splitlines():
        print(f"    {line}")
except Exception as e:
    print(f"  ❌ Command failed: {e}")

conn.disconnect()

# ── Step 6: Summary ──────────────────────────────────────────────────────────
print()
print("=" * 60)
print("  ✅ ALL STEPS PASSED — SSH is working!")
print("  The tool should be able to login now.")
print()
print("  If the tool still fails, check:")
print(f"    1. Your .env has: GNS3_SSH_USER={args.user}")
print(f"                      GNS3_SSH_PASS={args.password}")
print(f"                      GNS3_DEVICE_TYPE={args.type}")
print(f"    2. In the Devices tab, use '✏️ Set credentials' to")
print(f"       enter {args.user}/{args.password} and click 💾 Save")
print("=" * 60)
