"""
router_login_check.py
=====================

A single function, validate_router_login(), that the Streamlit UI calls when the
user clicks "Test Router Login". It performs the same staged checks as the
standalone scripts/validate_router_login.py, but returns a structured result
(list of steps) instead of printing — so the UI can render it nicely.

NOTHING on the router is changed: only TCP connect, login, and read-only
commands (plus enter/exit config mode to prove privilege).
"""
from __future__ import annotations

import socket
from typing import Dict, List, Any


def _step(name: str, ok: bool, detail: str = "") -> Dict[str, Any]:
    return {"name": name, "ok": ok, "detail": detail}


def validate_router_login(
    host: str,
    port: str,
    username: str = "admin",
    password: str = "admin",
    device_type: str = "cisco_ios",
    timeout: int = 15,
) -> Dict[str, Any]:
    """
    Returns a dict:
      {
        "success": bool,            # overall: login worked AND config mode worked
        "can_login": bool,
        "can_config": bool,
        "steps": [ {name, ok, detail}, ... ],
        "prompt": str,
        "interfaces": str,          # 'show ip interface brief' output (read-only)
        "summary": str,             # one-line human verdict
      }
    """
    steps: List[Dict[str, Any]] = []
    result: Dict[str, Any] = {
        "success": False,
        "can_login": False,
        "can_config": False,
        "steps": steps,
        "prompt": "",
        "interfaces": "",
        "summary": "",
    }

    host = (host or "").strip()
    port = (port or "").strip()

    # Step 0: inputs
    if not host or not port:
        steps.append(_step("Inputs provided", False,
                           "Host and port are required. Start the Pinggy tunnel and paste its host + port."))
        result["summary"] = "Missing tunnel host/port."
        return result
    try:
        port_i = int(port)
    except ValueError:
        steps.append(_step("Inputs provided", False, f"Port '{port}' is not a number."))
        result["summary"] = "Port must be a number."
        return result
    steps.append(_step("Inputs provided", True, f"{host}:{port_i}"))

    # Step 1: TCP reachability
    try:
        with socket.create_connection((host, port_i), timeout=timeout):
            pass
        steps.append(_step("Tunnel reachable (TCP)", True, "Something is listening on the tunnel."))
    except socket.timeout:
        steps.append(_step("Tunnel reachable (TCP)", False,
                           "Timed out. Is the Pinggy command still running on the GNS3 host?"))
        result["summary"] = "Tunnel not responding (timeout)."
        return result
    except socket.gaierror:
        steps.append(_step("Tunnel reachable (TCP)", False,
                           f"Could not resolve '{host}'. Check the Pinggy URL spelling."))
        result["summary"] = "Could not resolve tunnel host."
        return result
    except ConnectionRefusedError:
        steps.append(_step("Tunnel reachable (TCP)", False,
                           "Refused. Pinggy is up but not forwarding to the router's SSH port."))
        result["summary"] = "Tunnel up but nothing forwarded to the router."
        return result
    except Exception as e:
        steps.append(_step("Tunnel reachable (TCP)", False, str(e)))
        result["summary"] = f"TCP error: {e}"
        return result

    # Step 2: netmiko present
    try:
        # Loosen SSH algorithms for older Cisco IOS (15.x) which negotiates
        # legacy KEX/ciphers that modern paramiko disables by default. Without
        # this, the SSH handshake to old IOS times out.
        try:
            import paramiko
            paramiko.Transport._preferred_kex = (
                "diffie-hellman-group14-sha1",
                "diffie-hellman-group-exchange-sha1",
                "diffie-hellman-group1-sha1",
            )
            paramiko.Transport._preferred_ciphers = (
                "aes128-cbc", "aes192-cbc", "aes256-cbc",
                "aes128-ctr", "aes192-ctr", "aes256-ctr",
            )
            paramiko.Transport._preferred_keys = (
                "ssh-rsa", "rsa-sha2-512", "rsa-sha2-256",
            )
        except Exception:
            pass

        from netmiko import (
            ConnectHandler,
            NetmikoAuthenticationException,
            NetmikoTimeoutException,
        )
        steps.append(_step("SSH library (netmiko)", True, "Ready (legacy IOS algorithms enabled)."))
    except ImportError:
        steps.append(_step("SSH library (netmiko)", False,
                           "netmiko not installed in this app environment. Add 'netmiko' to requirements.txt."))
        result["summary"] = "netmiko not installed."
        return result

    # Step 3: login + read-only checks
    is_telnet = device_type.endswith("_telnet")
    conn_config = {
        "device_type": device_type,
        "host": host,
        "port": port_i,
        "password": password,
        "secret": password,
        "fast_cli": False,
        "conn_timeout": 30,
        "banner_timeout": 30,
        "auth_timeout": 30,
        "blocking_timeout": 30,
    }
    # SSH always needs a username; a GNS3 Telnet console usually does NOT
    # (login is configured on the console line, or there's no login at all).
    if is_telnet:
        if username:
            conn_config["username"] = username
        login_label = "Console login (telnet)" if not username else f"Console login as '{username}'"
    else:
        conn_config["username"] = username
        login_label = f"Login as '{username}'"
    try:
        with ConnectHandler(**conn_config) as conn:
            prompt = conn.find_prompt()
            result["prompt"] = prompt
            result["can_login"] = True
            steps.append(_step(login_label, True, f"Device prompt: {prompt}"))

            try:
                brief = conn.send_command("show ip interface brief", read_timeout=15)
                result["interfaces"] = brief
            except Exception as e:
                result["interfaces"] = f"(could not read interfaces: {e})"

            # Prove config mode (then exit) — required for applying fixes later.
            try:
                conn.config_mode()
                result["can_config"] = conn.check_config_mode()
                conn.exit_config_mode()
            except Exception as e:
                result["can_config"] = False
                steps.append(_step("Reach config mode", False,
                                   f"Could not enter config mode: {e}"))

            if result["can_config"]:
                steps.append(_step("Reach config mode", True,
                                   "Account can apply fixes (privilege OK)."))

        if result["can_login"] and result["can_config"]:
            result["success"] = True
            result["summary"] = "Validated — the platform can log in AND apply fixes."
        elif result["can_login"]:
            result["summary"] = ("Login works, but config mode failed. "
                                 "The admin user needs privilege 15 to apply fixes.")
        return result

    except NetmikoAuthenticationException:
        steps.append(_step(login_label, False,
                           "Rejected. Tunnel is fine but the username/password was refused."))
        result["summary"] = "Login rejected — check credentials."
        return result
    except NetmikoTimeoutException:
        steps.append(_step(login_label, False,
                           "Handshake timed out. If the router is Telnet-only, use device type 'cisco_ios_telnet'."))
        result["summary"] = "Login handshake timed out."
        return result
    except Exception as e:
        steps.append(_step(login_label, False, str(e)))
        result["summary"] = f"Unexpected error: {e}"
        return result
