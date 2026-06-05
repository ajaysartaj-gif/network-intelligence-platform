"""
GNS3 REST API Engine.
Connects to GNS3 server (localhost:3080 by default), fetches topology,
node console ports, and device status. Falls back gracefully when unavailable.
"""
from __future__ import annotations
import requests
import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class GNS3Node:
    node_id: str
    name: str
    node_type: str        # qemu, dynamips, docker, etc.
    status: str           # started, stopped, suspended
    console_host: str
    console_port: Optional[int]
    console_type: str     # telnet, vnc, spice, none
    x: float = 0.0
    y: float = 0.0
    properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GNS3Link:
    link_id: str
    node_a: str
    interface_a: str
    node_b: str
    interface_b: str
    capturing: bool = False


class GNS3Engine:
    """
    Integrates with GNS3 REST API v2 to fetch live topology and build
    Netmiko connection configs for autonomous remediation.
    """

    def __init__(self, host: str = "localhost", port: int = 3080):
        self.base_url = f"http://{host}:{port}/v2"
        self.available = False
        self.active_project_id: Optional[str] = None
        self.nodes: Dict[str, GNS3Node] = {}     # name → GNS3Node
        self.links: List[GNS3Link] = []
        self.version: str = "unknown"
        self._check_connectivity()

    # ── connectivity ────────────────────────────────────────────────

    def _check_connectivity(self) -> None:
        try:
            r = requests.get(f"{self.base_url}/version", timeout=2)
            if r.status_code == 200:
                self.available = True
                self.version = r.json().get("version", "unknown")
                logger.info(f"GNS3 connected — version {self.version}")
                self.load_project()
            else:
                logger.debug(f"GNS3 returned HTTP {r.status_code} — not connected")
        except Exception as e:
            logger.info(f"GNS3 not reachable ({e}); running in simulation mode")

    # ── project loading ──────────────────────────────────────────────

    def get_projects(self) -> List[Dict[str, Any]]:
        if not self.available:
            return []
        try:
            r = requests.get(f"{self.base_url}/projects", timeout=5)
            return r.json() if r.status_code == 200 else []
        except Exception:
            return []

    def load_project(self, project_id: Optional[str] = None) -> bool:
        """Load specified project, or first open project found."""
        projects = self.get_projects()
        if not projects:
            return False

        if project_id:
            target = next((p for p in projects if p["project_id"] == project_id), None)
        else:
            target = next((p for p in projects if p.get("status") == "opened"), None)
            if not target:
                target = projects[0]

        if not target:
            return False

        self.active_project_id = target["project_id"]
        self._load_nodes()
        self._load_links()
        logger.info(f"Loaded GNS3 project: {target.get('name', self.active_project_id)}")
        return True

    def _load_nodes(self) -> None:
        if not self.active_project_id:
            return
        try:
            r = requests.get(
                f"{self.base_url}/projects/{self.active_project_id}/nodes",
                timeout=5,
            )
            if r.status_code == 200:
                self.nodes = {}
                for n in r.json():
                    node = GNS3Node(
                        node_id=n["node_id"],
                        name=n["name"],
                        node_type=n.get("node_type", "unknown"),
                        status=n.get("status", "unknown"),
                        console_host=n.get("console_host", "127.0.0.1"),
                        console_port=n.get("console"),
                        console_type=n.get("console_type", "telnet"),
                        x=float(n.get("x", 0)),
                        y=float(n.get("y", 0)),
                        properties=n.get("properties", {}),
                    )
                    self.nodes[n["name"]] = node
                logger.info(f"Loaded {len(self.nodes)} GNS3 nodes")
        except Exception as e:
            logger.error(f"Failed to load GNS3 nodes: {e}")

    def _load_links(self) -> None:
        if not self.active_project_id:
            return
        try:
            r = requests.get(
                f"{self.base_url}/projects/{self.active_project_id}/links",
                timeout=5,
            )
            if r.status_code == 200:
                self.links = []
                id_to_name = {n.node_id: name for name, n in self.nodes.items()}
                for lnk in r.json():
                    ends = lnk.get("nodes", [])
                    if len(ends) >= 2:
                        self.links.append(GNS3Link(
                            link_id=lnk["link_id"],
                            node_a=id_to_name.get(ends[0]["node_id"], ends[0]["node_id"]),
                            interface_a=ends[0].get("label", {}).get("text", ""),
                            node_b=id_to_name.get(ends[1]["node_id"], ends[1]["node_id"]),
                            interface_b=ends[1].get("label", {}).get("text", ""),
                            capturing=lnk.get("capturing", False),
                        ))
                logger.info(f"Loaded {len(self.links)} GNS3 links")
        except Exception as e:
            logger.error(f"Failed to load GNS3 links: {e}")

    # ── netmiko config builder ───────────────────────────────────────

    def get_netmiko_config(
        self,
        node_name: str,
        device_type: str = "cisco_ios_telnet",
        username: str = "",
        password: str = "",
        secret: str = "",
    ) -> Optional[Dict[str, Any]]:
        """Build Netmiko connection dict for a GNS3 node via telnet console."""
        node = self.nodes.get(node_name)
        if not node or not node.console_port:
            return None
        return {
            "device_type": device_type,
            "host": node.console_host,
            "port": node.console_port,
            "username": username,
            "password": password,
            "secret": secret,
            "timeout": 15,
            "session_timeout": 60,
            "global_delay_factor": 2,
        }

    # ── node control ─────────────────────────────────────────────────

    def start_node(self, node_name: str) -> bool:
        node = self.nodes.get(node_name)
        if not node or not self.available or not self.active_project_id:
            return False
        try:
            r = requests.post(
                f"{self.base_url}/projects/{self.active_project_id}/nodes/{node.node_id}/start",
                timeout=10,
            )
            return r.status_code in (200, 201, 204)
        except Exception:
            return False

    def stop_node(self, node_name: str) -> bool:
        node = self.nodes.get(node_name)
        if not node or not self.available or not self.active_project_id:
            return False
        try:
            r = requests.post(
                f"{self.base_url}/projects/{self.active_project_id}/nodes/{node.node_id}/stop",
                timeout=10,
            )
            return r.status_code in (200, 201, 204)
        except Exception:
            return False

    def refresh(self) -> None:
        if self.available and self.active_project_id:
            self._load_nodes()
            self._load_links()

    # ── summary ──────────────────────────────────────────────────────

    def get_topology_summary(self) -> Dict[str, Any]:
        return {
            "available": self.available,
            "version": self.version,
            "project_id": self.active_project_id,
            "total_nodes": len(self.nodes),
            "total_links": len(self.links),
            "running_nodes": sum(1 for n in self.nodes.values() if n.status == "started"),
            "stopped_nodes": sum(1 for n in self.nodes.values() if n.status == "stopped"),
            "nodes": [
                {
                    "name": n.name,
                    "type": n.node_type,
                    "status": n.status,
                    "console_port": n.console_port,
                    "x": n.x,
                    "y": n.y,
                }
                for n in self.nodes.values()
            ],
            "links": [
                {
                    "from": lnk.node_a,
                    "to": lnk.node_b,
                    "interface_a": lnk.interface_a,
                    "interface_b": lnk.interface_b,
                }
                for lnk in self.links
            ],
        }
