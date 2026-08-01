"""
core/multi_device_orchestrator.py
==================================
Coordinate fixes across multiple network devices automatically.

Handles dependencies, parallelizes where safe, rolls back atomically on failure.
"""

import logging
import asyncio
from dataclasses import dataclass, field
from typing import List, Dict, Set, Any, Optional
import networkx as nx

logger = logging.getLogger(__name__)


@dataclass
class DeviceCommand:
    """Single command batch for a device."""
    device: str
    commands: List[str]
    rollback_commands: List[str] = field(default_factory=list)
    depends_on: List[str] = field(default_factory=list)  # Device names that must execute first
    verification_commands: List[str] = field(default_factory=list)
    description: str = ""  # What this change does


@dataclass
class ExecutionResult:
    """Result of executing commands on a single device."""
    device: str
    status: str  # "success" | "failed" | "rollback"
    commands_executed: int
    duration_seconds: float
    error: Optional[str] = None
    output: Optional[str] = None


class MultiDeviceOrchestrator:
    """Coordinate and execute fixes across multiple network devices."""

    def __init__(self, topology_graph: Optional[Any] = None,
                 executor: Optional[Any] = None):
        """
        Parameters
        ----------
        topology_graph : networkx.Graph, optional
            Network topology for dependency inference
        executor : RemediationExecutor, optional
            Executor for running commands on devices
        """
        self.topology = topology_graph
        self.executor = executor
        logger.info("MultiDeviceOrchestrator initialized")

    def execute_coordinated_fix(self,
                               device_commands: List[DeviceCommand]) -> Dict[str, ExecutionResult]:
        """
        Execute commands on multiple devices in optimal order.

        Ensures:
        1. Dependencies honored (PE before CE)
        2. Parallel execution where safe
        3. Atomic rollback on failure

        Parameters
        ----------
        device_commands : List[DeviceCommand]
            Commands to execute on each device

        Returns
        -------
        Dict[str, ExecutionResult]
            Results keyed by device name
        """
        logger.info(f"Starting coordinated execution on {len(device_commands)} devices")

        # STEP 1: Build dependency graph
        dag = self._build_dependency_graph(device_commands)

        # STEP 2: Topological sort for optimal order
        try:
            execution_order = list(nx.topological_sort(dag))
            logger.info(f"Execution order: {execution_order}")
        except nx.NetworkXError as e:
            logger.error(f"Circular dependency detected: {e}")
            return {}

        # STEP 3: Identify parallelizable levels
        levels = self._identify_parallelizable_levels(dag)
        logger.info(f"Identified {len(levels)} execution levels")
        for i, level in enumerate(levels):
            logger.info(f"  Level {i+1}: {level}")

        # STEP 4: Execute with rollback on failure
        results = {}
        executed_devices = []

        try:
            for level_num, level in enumerate(levels, 1):
                logger.info(f"Executing level {level_num}/{len(levels)}: {level}")

                # Execute all devices in this level in parallel
                level_results = asyncio.run(
                    self._execute_level_parallel(level, device_commands)
                )

                results.update(level_results)
                executed_devices.extend(level)

                # Check for failures
                failures = [r for r in level_results.values() if r.status == "failed"]
                if failures:
                    logger.error(f"Level {level_num} execution failed: {len(failures)} device(s)")
                    raise Exception(f"Execution failed on {[f.device for f in failures]}")

                logger.info(f"Level {level_num} completed successfully")

        except Exception as e:
            logger.error(f"Execution failed: {e}, triggering atomic rollback...")
            rollback_results = asyncio.run(
                self._rollback_executed_devices(executed_devices, device_commands)
            )
            logger.warning(f"Rollback completed on {len(rollback_results)} device(s)")
            raise

        logger.info(f"Coordinated execution completed successfully on {len(results)} device(s)")
        return results

    def _build_dependency_graph(self, device_commands: List[DeviceCommand]) -> nx.DiGraph:
        """Build DAG of device dependencies."""
        dag = nx.DiGraph()

        # Add all devices as nodes
        for cmd in device_commands:
            dag.add_node(cmd.device)

            # Add edges for dependencies (dependency must execute first)
            if cmd.depends_on:
                for dep in cmd.depends_on:
                    dag.add_edge(dep, cmd.device)

        return dag

    def _identify_parallelizable_levels(self, dag: nx.DiGraph) -> List[List[str]]:
        """
        Partition devices into levels where each level can execute in parallel.

        Example:
          Level 1: [PE1, PE2] (no dependencies)
          Level 2: [CE1, CE2] (depends on Level 1)
        """
        levels = []
        dag_copy = dag.copy()

        while dag_copy.nodes():
            # Find nodes with no incoming edges (no dependencies)
            level = [n for n in dag_copy.nodes() if dag_copy.in_degree(n) == 0]

            if not level:
                # Circular dependency (shouldn't happen if build_graph works right)
                logger.error("Circular dependency detected in graph")
                break

            levels.append(level)

            # Remove these nodes for next iteration
            dag_copy.remove_nodes_from(level)

        return levels

    async def _execute_level_parallel(self,
                                     devices: List[str],
                                     device_commands: List[DeviceCommand]) -> Dict[str, ExecutionResult]:
        """Execute commands on all devices in level in parallel."""
        tasks = []
        device_map = {}

        for device in devices:
            cmd = next((c for c in device_commands if c.device == device), None)
            if cmd:
                device_map[device] = cmd
                task = self._execute_on_device(cmd)
                tasks.append(task)

        results = await asyncio.gather(*tasks, return_exceptions=True)

        output = {}
        for device, result in zip(devices, results):
            if isinstance(result, Exception):
                output[device] = ExecutionResult(
                    device=device,
                    status="failed",
                    commands_executed=0,
                    duration_seconds=0.0,
                    error=str(result)
                )
            else:
                output[device] = result

        return output

    async def _execute_on_device(self, cmd: DeviceCommand) -> ExecutionResult:
        """Execute commands on a single device (simulated)."""
        import time

        logger.info(f"Executing on {cmd.device}: {len(cmd.commands)} command(s)")
        logger.debug(f"  Description: {cmd.description}")

        start_time = time.time()

        try:
            # In real implementation, use self.executor.execute_async()
            # For now, simulate execution
            if self.executor:
                result = await self.executor.execute_async(cmd.device, cmd.commands)
                status = result.get("status", "success")
            else:
                # Simulated execution
                await asyncio.sleep(0.1)  # Simulate network delay
                status = "success"

            duration = time.time() - start_time

            logger.info(f"Execution on {cmd.device} completed in {duration:.2f}s")

            return ExecutionResult(
                device=cmd.device,
                status="success" if status == "success" else "failed",
                commands_executed=len(cmd.commands),
                duration_seconds=duration,
            )

        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"Execution on {cmd.device} failed: {e}")

            return ExecutionResult(
                device=cmd.device,
                status="failed",
                commands_executed=0,
                duration_seconds=duration,
                error=str(e)
            )

    async def _rollback_executed_devices(self,
                                        devices: List[str],
                                        device_commands: List[DeviceCommand]) -> Dict[str, ExecutionResult]:
        """Rollback changes on all executed devices in reverse order."""
        logger.warning(f"Rolling back changes on {len(devices)} device(s)")

        # Reverse order for rollback (last executed first)
        devices_reversed = list(reversed(devices))

        tasks = []
        for device in devices_reversed:
            cmd = next((c for c in device_commands if c.device == device), None)
            if cmd and cmd.rollback_commands:
                logger.info(f"Rolling back {device}: {len(cmd.rollback_commands)} command(s)")
                task = self._execute_on_device(
                    DeviceCommand(
                        device=device,
                        commands=cmd.rollback_commands,
                        description=f"ROLLBACK: {cmd.description}"
                    )
                )
                tasks.append(task)

        results = await asyncio.gather(*tasks, return_exceptions=True)

        output = {}
        for device, result in zip(devices_reversed, results):
            if isinstance(result, Exception):
                output[device] = ExecutionResult(
                    device=device,
                    status="rollback",
                    commands_executed=0,
                    duration_seconds=0.0,
                    error=str(result)
                )
            else:
                output[device] = result

        logger.info("Rollback completed")
        return output

    def suggest_device_order(self,
                            device_list: List[str]) -> List[str]:
        """
        Suggest optimal execution order based on topology.

        Uses topology to infer dependencies:
        - Route reflectors (core) should execute first
        - Customer edges should execute after
        """
        if not self.topology:
            return device_list

        # Infer device roles from topology
        # Route reflectors: high degree (connected to many)
        # Customer edges: low degree

        device_degrees = {d: self.topology.degree(d)
                         for d in device_list
                         if d in self.topology.nodes()}

        if not device_degrees:
            return device_list

        # Sort: high degree first (core devices), then low degree (edge devices)
        sorted_devices = sorted(device_list,
                              key=lambda d: device_degrees.get(d, 0),
                              reverse=True)

        logger.info(f"Suggested device order: {sorted_devices}")
        return sorted_devices

    def print_execution_plan(self,
                            device_commands: List[DeviceCommand]) -> str:
        """Generate a human-readable execution plan."""
        dag = self._build_dependency_graph(device_commands)
        levels = self._identify_parallelizable_levels(dag)

        plan = "📋 EXECUTION PLAN\n"
        plan += "=" * 50 + "\n\n"

        for i, level in enumerate(levels, 1):
            if len(level) == 1:
                plan += f"Step {i}: Execute on {level[0]}\n"
            else:
                plan += f"Step {i}: Execute in PARALLEL on: {', '.join(level)}\n"

            for device in level:
                cmd = next((c for c in device_commands if c.device == device), None)
                if cmd:
                    plan += f"  └─ {cmd.description or 'No description'}\n"
                    plan += f"     Commands: {len(cmd.commands)}\n"
                    plan += f"     Rollback: {len(cmd.rollback_commands)}\n"

            plan += "\n"

        plan += "=" * 50 + "\n"
        plan += f"Total: {len(device_commands)} device(s), {len(levels)} step(s)\n"

        return plan
