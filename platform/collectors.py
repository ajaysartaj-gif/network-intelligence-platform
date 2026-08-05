"""
Multi-Domain Data Collectors

Discovers systems and dependencies across all infrastructure domains:
- Routing (devices, protocols)
- Cloud (AWS, Azure, GCP)
- Containers (Kubernetes)
- Applications (services, APIs)
- Storage (SAN, databases)
"""

from typing import Dict, List, Tuple, Any, Optional
from dataclasses import dataclass
from abc import ABC, abstractmethod
from enum import Enum
import json


class CollectorType(Enum):
    """Types of data collectors."""
    AWS = "aws"
    KUBERNETES = "kubernetes"
    NETWORK_DEVICE = "network_device"
    CMDB = "cmdb"
    OBSERVABILITY = "observability"


@dataclass
class DiscoveredSystem:
    """A system discovered by a collector."""
    system_id: str
    domain: str
    name: str
    type: str
    criticality: str
    metadata: Dict[str, Any]


@dataclass
class DiscoveredDependency:
    """A dependency discovered by a collector."""
    source_id: str
    target_id: str
    dep_type: str
    confidence: float
    description: str


class Collector(ABC):
    """Base class for all data collectors."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.systems: List[DiscoveredSystem] = []
        self.dependencies: List[DiscoveredDependency] = []

    @abstractmethod
    def connect(self) -> bool:
        """Establish connection to data source."""
        raise NotImplementedError

    @abstractmethod
    def discover(self) -> Tuple[List[DiscoveredSystem], List[DiscoveredDependency]]:
        """Discover systems and dependencies."""
        raise NotImplementedError

    def disconnect(self):
        """Disconnect from data source."""
        pass


class AWSCollector(Collector):
    """Discovers AWS infrastructure (VPCs, route tables, Direct Connect, etc.)."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.region = config.get("region", "us-east-1")
        self.account_id = config.get("account_id")
        self.connected = False
        # In real implementation: import boto3

    def connect(self) -> bool:
        """Connect to AWS."""
        try:
            # In production: connect to AWS API
            # client = boto3.client('ec2', region_name=self.region)
            self.connected = True
            return True
        except Exception as e:
            print(f"Failed to connect to AWS: {e}")
            return False

    def discover(self) -> Tuple[List[DiscoveredSystem], List[DiscoveredDependency]]:
        """Discover AWS infrastructure."""
        systems = []
        dependencies = []

        if not self.connected:
            return systems, dependencies

        # Discover VPCs
        vpc_systems = self._discover_vpcs()
        systems.extend(vpc_systems)

        # Discover route tables
        rt_systems = self._discover_route_tables()
        systems.extend(rt_systems)

        # Discover Direct Connect
        dx_systems = self._discover_direct_connect()
        systems.extend(dx_systems)

        # Discover EC2 instances
        ec2_systems = self._discover_ec2()
        systems.extend(ec2_systems)

        # Discover dependencies
        dependencies.extend(self._discover_vpc_dependencies())
        dependencies.extend(self._discover_routing_dependencies())
        dependencies.extend(self._discover_connectivity_dependencies())

        self.systems = systems
        self.dependencies = dependencies
        return systems, dependencies

    def _discover_vpcs(self) -> List[DiscoveredSystem]:
        """Discover VPCs."""
        # In production: call AWS EC2 API
        # vpcs = ec2_client.describe_vpcs()

        # Mock implementation for demo
        return [
            DiscoveredSystem(
                system_id="aws-vpc-prod",
                domain="cloud",
                name="Production VPC",
                type="vpc",
                criticality="critical",
                metadata={
                    "cidr": "10.0.0.0/16",
                    "account": self.account_id,
                    "region": self.region,
                    "dns_support": True,
                    "dns_hostnames": True
                }
            ),
            DiscoveredSystem(
                system_id="aws-vpc-staging",
                domain="cloud",
                name="Staging VPC",
                type="vpc",
                criticality="high",
                metadata={
                    "cidr": "10.1.0.0/16",
                    "account": self.account_id,
                    "region": self.region
                }
            )
        ]

    def _discover_route_tables(self) -> List[DiscoveredSystem]:
        """Discover route tables."""
        return [
            DiscoveredSystem(
                system_id="aws-rt-prod-main",
                domain="cloud",
                name="Production Main Route Table",
                type="route_table",
                criticality="critical",
                metadata={
                    "vpc": "aws-vpc-prod",
                    "routes": 47,
                    "propagation_enabled": True
                }
            ),
            DiscoveredSystem(
                system_id="aws-rt-prod-private",
                domain="cloud",
                name="Production Private Route Table",
                type="route_table",
                criticality="critical",
                metadata={
                    "vpc": "aws-vpc-prod",
                    "routes": 12,
                    "nat_gateway": "nat-12345"
                }
            )
        ]

    def _discover_direct_connect(self) -> List[DiscoveredSystem]:
        """Discover Direct Connect connections."""
        return [
            DiscoveredSystem(
                system_id="aws-dx-prod",
                domain="cloud",
                name="Production Direct Connect",
                type="direct_connect",
                criticality="critical",
                metadata={
                    "bandwidth": "10Gbps",
                    "location": "us-east-1a",
                    "state": "available",
                    "vlan": 100,
                    "asn": 65100
                }
            )
        ]

    def _discover_ec2(self) -> List[DiscoveredSystem]:
        """Discover EC2 instances."""
        return [
            DiscoveredSystem(
                system_id="aws-ec2-api-server-1",
                domain="application",
                name="API Server 1",
                type="ec2_instance",
                criticality="high",
                metadata={
                    "vpc": "aws-vpc-prod",
                    "instance_type": "t3.large",
                    "state": "running"
                }
            ),
            DiscoveredSystem(
                system_id="aws-ec2-api-server-2",
                domain="application",
                name="API Server 2",
                type="ec2_instance",
                criticality="high",
                metadata={
                    "vpc": "aws-vpc-prod",
                    "instance_type": "t3.large",
                    "state": "running"
                }
            )
        ]

    def _discover_vpc_dependencies(self) -> List[DiscoveredDependency]:
        """Discover VPC-internal dependencies."""
        return [
            DiscoveredDependency(
                source_id="aws-vpc-prod",
                target_id="aws-rt-prod-main",
                dep_type="routing",
                confidence=0.99,
                description="VPC routes through main route table"
            ),
            DiscoveredDependency(
                source_id="aws-rt-prod-main",
                target_id="aws-rt-prod-private",
                dep_type="redundancy",
                confidence=0.95,
                description="Private subnets have alternative routing"
            )
        ]

    def _discover_routing_dependencies(self) -> List[DiscoveredDependency]:
        """Discover routing dependencies."""
        return [
            DiscoveredDependency(
                source_id="aws-dx-prod",
                target_id="aws-vpc-prod",
                dep_type="connectivity",
                confidence=0.99,
                description="Direct Connect provides connectivity to VPC"
            )
        ]

    def _discover_connectivity_dependencies(self) -> List[DiscoveredDependency]:
        """Discover EC2 to VPC dependencies."""
        return [
            DiscoveredDependency(
                source_id="aws-vpc-prod",
                target_id="aws-ec2-api-server-1",
                dep_type="compute_dependency",
                confidence=0.99,
                description="EC2 instance depends on VPC"
            ),
            DiscoveredDependency(
                source_id="aws-vpc-prod",
                target_id="aws-ec2-api-server-2",
                dep_type="compute_dependency",
                confidence=0.99,
                description="EC2 instance depends on VPC"
            )
        ]


class KubernetesCollector(Collector):
    """Discovers Kubernetes infrastructure (clusters, services, policies, etc.)."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.cluster_name = config.get("cluster_name", "default")
        self.context = config.get("context")
        self.connected = False
        # In real implementation: from kubernetes import client

    def connect(self) -> bool:
        """Connect to Kubernetes cluster."""
        try:
            # In production: connect to Kubernetes API
            # kubernetes.config.load_kube_config(context=self.context)
            self.connected = True
            return True
        except Exception as e:
            print(f"Failed to connect to Kubernetes: {e}")
            return False

    def discover(self) -> Tuple[List[DiscoveredSystem], List[DiscoveredDependency]]:
        """Discover Kubernetes infrastructure."""
        systems = []
        dependencies = []

        if not self.connected:
            return systems, dependencies

        # Discover cluster
        cluster_systems = self._discover_cluster()
        systems.extend(cluster_systems)

        # Discover namespaces
        ns_systems = self._discover_namespaces()
        systems.extend(ns_systems)

        # Discover services
        svc_systems = self._discover_services()
        systems.extend(svc_systems)

        # Discover deployments
        deploy_systems = self._discover_deployments()
        systems.extend(deploy_systems)

        # Discover network policies
        np_systems = self._discover_network_policies()
        systems.extend(np_systems)

        # Discover dependencies
        dependencies.extend(self._discover_service_dependencies())
        dependencies.extend(self._discover_network_policy_dependencies())
        dependencies.extend(self._discover_workload_dependencies())

        self.systems = systems
        self.dependencies = dependencies
        return systems, dependencies

    def _discover_cluster(self) -> List[DiscoveredSystem]:
        """Discover Kubernetes cluster."""
        return [
            DiscoveredSystem(
                system_id=f"k8s-cluster-{self.cluster_name}",
                domain="container",
                name=f"Kubernetes Cluster ({self.cluster_name})",
                type="kubernetes_cluster",
                criticality="critical",
                metadata={
                    "context": self.context,
                    "version": "1.27.0",
                    "nodes": 3,
                    "namespaces": 5
                }
            )
        ]

    def _discover_namespaces(self) -> List[DiscoveredSystem]:
        """Discover namespaces."""
        return [
            DiscoveredSystem(
                system_id="k8s-ns-prod",
                domain="container",
                name="Production Namespace",
                type="namespace",
                criticality="critical",
                metadata={"pods": 42, "services": 8}
            ),
            DiscoveredSystem(
                system_id="k8s-ns-system",
                domain="container",
                name="System Namespace",
                type="namespace",
                criticality="critical",
                metadata={"pods": 12, "services": 3}
            )
        ]

    def _discover_services(self) -> List[DiscoveredSystem]:
        """Discover Kubernetes services."""
        return [
            DiscoveredSystem(
                system_id="k8s-svc-api-gateway",
                domain="application",
                name="API Gateway Service",
                type="kubernetes_service",
                criticality="critical",
                metadata={
                    "namespace": "k8s-ns-prod",
                    "type": "LoadBalancer",
                    "endpoints": 3,
                    "port": 443
                }
            ),
            DiscoveredSystem(
                system_id="k8s-svc-database",
                domain="application",
                name="Database Service",
                type="kubernetes_service",
                criticality="critical",
                metadata={
                    "namespace": "k8s-ns-prod",
                    "type": "ClusterIP",
                    "endpoints": 1,
                    "port": 5432
                }
            )
        ]

    def _discover_deployments(self) -> List[DiscoveredSystem]:
        """Discover deployments."""
        return [
            DiscoveredSystem(
                system_id="k8s-deploy-api",
                domain="application",
                name="API Deployment",
                type="deployment",
                criticality="critical",
                metadata={
                    "namespace": "k8s-ns-prod",
                    "replicas": 3,
                    "ready": 3,
                    "containers": 1
                }
            ),
            DiscoveredSystem(
                system_id="k8s-deploy-worker",
                domain="application",
                name="Worker Deployment",
                type="deployment",
                criticality="high",
                metadata={
                    "namespace": "k8s-ns-prod",
                    "replicas": 2,
                    "ready": 2
                }
            )
        ]

    def _discover_network_policies(self) -> List[DiscoveredSystem]:
        """Discover network policies."""
        return [
            DiscoveredSystem(
                system_id="k8s-netpol-api-ingress",
                domain="security",
                name="API Ingress Policy",
                type="network_policy",
                criticality="high",
                metadata={
                    "namespace": "k8s-ns-prod",
                    "pod_selector": "app=api",
                    "ingress_rules": 2
                }
            )
        ]

    def _discover_service_dependencies(self) -> List[DiscoveredDependency]:
        """Discover service-to-service dependencies."""
        return [
            DiscoveredDependency(
                source_id="k8s-svc-api-gateway",
                target_id="k8s-svc-database",
                dep_type="connectivity",
                confidence=0.99,
                description="API gateway depends on database service"
            ),
            DiscoveredDependency(
                source_id="k8s-deploy-api",
                target_id="k8s-svc-api-gateway",
                dep_type="service_mesh",
                confidence=0.95,
                description="API pods use API gateway service"
            )
        ]

    def _discover_network_policy_dependencies(self) -> List[DiscoveredDependency]:
        """Discover network policy dependencies."""
        return [
            DiscoveredDependency(
                source_id="k8s-netpol-api-ingress",
                target_id="k8s-deploy-api",
                dep_type="security_policy",
                confidence=0.98,
                description="Network policy guards API deployment"
            )
        ]

    def _discover_workload_dependencies(self) -> List[DiscoveredDependency]:
        """Discover workload dependencies."""
        return [
            DiscoveredDependency(
                source_id="k8s-deploy-api",
                target_id="k8s-svc-database",
                dep_type="workload_dependency",
                confidence=0.95,
                description="API pods need database connectivity"
            )
        ]


class NetworkDeviceCollector(Collector):
    """Discovers network devices and their relationships (routers, switches)."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.device_list = config.get("devices", [])
        self.connected = False

    def connect(self) -> bool:
        """Connect to network devices."""
        try:
            # In production: verify connectivity to all devices
            self.connected = True
            return True
        except Exception as e:
            print(f"Failed to connect to devices: {e}")
            return False

    def discover(self) -> Tuple[List[DiscoveredSystem], List[DiscoveredDependency]]:
        """Discover network infrastructure."""
        systems = []
        dependencies = []

        if not self.connected:
            return systems, dependencies

        systems.extend(self._discover_routers())
        systems.extend(self._discover_switches())
        dependencies.extend(self._discover_routing_protocols())
        dependencies.extend(self._discover_switching_dependencies())

        self.systems = systems
        self.dependencies = dependencies
        return systems, dependencies

    def _discover_routers(self) -> List[DiscoveredSystem]:
        """Discover routers."""
        return [
            DiscoveredSystem(
                system_id="router-core-1",
                domain="routing",
                name="Core Router 1",
                type="router",
                criticality="critical",
                metadata={
                    "model": "Cisco ASR 9010",
                    "ios": "16.9.4",
                    "uptime": "365 days",
                    "interfaces": 48
                }
            ),
            DiscoveredSystem(
                system_id="router-edge-1",
                domain="routing",
                name="Edge Router 1",
                type="router",
                criticality="high",
                metadata={
                    "model": "Cisco CSR 1000V",
                    "ios": "16.12.03",
                    "interfaces": 10
                }
            )
        ]

    def _discover_switches(self) -> List[DiscoveredSystem]:
        """Discover switches."""
        return [
            DiscoveredSystem(
                system_id="switch-access-1",
                domain="switching",
                name="Access Switch 1",
                type="switch",
                criticality="high",
                metadata={
                    "model": "Cisco Catalyst 9300",
                    "ports": 48,
                    "vlans": 12
                }
            )
        ]

    def _discover_routing_protocols(self) -> List[DiscoveredDependency]:
        """Discover routing protocol relationships."""
        return [
            DiscoveredDependency(
                source_id="router-core-1",
                target_id="router-edge-1",
                dep_type="ospf_peering",
                confidence=0.99,
                description="OSPF peering between core and edge"
            ),
            DiscoveredDependency(
                source_id="router-core-1",
                target_id="router-edge-1",
                dep_type="bgp_peering",
                confidence=0.98,
                description="BGP peering for route exchange"
            )
        ]

    def _discover_switching_dependencies(self) -> List[DiscoveredDependency]:
        """Discover switching relationships."""
        return [
            DiscoveredDependency(
                source_id="switch-access-1",
                target_id="router-edge-1",
                dep_type="uplink",
                confidence=0.99,
                description="Switch uplink to edge router"
            )
        ]


class CollectorManager:
    """Manages all data collectors and coordinates discovery."""

    def __init__(self):
        self.collectors: Dict[str, Collector] = {}

    def add_collector(self, name: str, collector: Collector) -> None:
        """Register a collector."""
        self.collectors[name] = collector

    def discover_all(self) -> Tuple[List[DiscoveredSystem], List[DiscoveredDependency]]:
        """Run all collectors and aggregate results."""
        all_systems: List[DiscoveredSystem] = []
        all_dependencies: List[DiscoveredDependency] = []

        for name, collector in self.collectors.items():
            if collector.connect():
                systems, dependencies = collector.discover()
                all_systems.extend(systems)
                all_dependencies.extend(dependencies)
                collector.disconnect()

        return all_systems, all_dependencies

    def discover_by_type(self, collector_type: CollectorType) -> Tuple[
        List[DiscoveredSystem], List[DiscoveredDependency]
    ]:
        """Run specific collector type."""
        all_systems: List[DiscoveredSystem] = []
        all_dependencies: List[DiscoveredDependency] = []

        for name, collector in self.collectors.items():
            # Match by collector class type
            if collector_type.value in name.lower():
                if collector.connect():
                    systems, dependencies = collector.discover()
                    all_systems.extend(systems)
                    all_dependencies.extend(dependencies)
                    collector.disconnect()

        return all_systems, all_dependencies

    def get_systems_by_domain(self, domain: str) -> List[DiscoveredSystem]:
        """Get systems discovered in a specific domain."""
        all_systems, _ = self.discover_all()
        return [s for s in all_systems if s.domain == domain]

    def get_statistics(self) -> Dict[str, Any]:
        """Get discovery statistics."""
        systems, dependencies = self.discover_all()

        systems_by_domain = {}
        for system in systems:
            domain = system.domain
            systems_by_domain[domain] = systems_by_domain.get(domain, 0) + 1

        return {
            "total_systems": len(systems),
            "total_dependencies": len(dependencies),
            "systems_by_domain": systems_by_domain,
            "average_confidence": (
                sum(d.confidence for d in dependencies) / len(dependencies)
                if dependencies else 0
            )
        }
