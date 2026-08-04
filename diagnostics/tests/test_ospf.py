"""
Tests for OSPF diagnostic engine.
"""

import pytest
from diagnostics.parsers.ospf import OSPFParser, NeighborState, NetworkType
from diagnostics.protocols.ospf import OSPFReasoner, RootCauseCategory
from diagnostics.pipeline import DiagnosticPipeline, DiagnosticInput


class TestOSPFParser:
    """Test OSPF output parser."""

    def test_parse_neighbor_exstart(self):
        """Test parsing neighbor in EXSTART state."""
        output = """Neighbor ID     Pri   State           Dead Time   Address         Interface
192.168.1.1       1   EXSTART/--      00:00:00    10.0.1.1        Gi0/0
"""
        neighbors = OSPFParser.parse_show_ip_ospf_neighbor(output)

        assert len(neighbors) == 1
        assert neighbors[0].neighbor_id == "192.168.1.1"
        assert neighbors[0].state == NeighborState.EXSTART
        assert neighbors[0].address == "10.0.1.1"
        assert neighbors[0].interface == "Gi0/0"

    def test_parse_neighbor_full(self):
        """Test parsing neighbor in FULL state."""
        output = """Neighbor ID     Pri   State           Dead Time   Address         Interface
192.168.1.1       1   FULL/BDR        00:00:35    10.0.1.1        Gi0/0
"""
        neighbors = OSPFParser.parse_show_ip_ospf_neighbor(output)

        assert len(neighbors) == 1
        assert neighbors[0].state == NeighborState.FULL

    def test_parse_multiple_neighbors(self):
        """Test parsing multiple neighbors."""
        output = """Neighbor ID     Pri   State           Dead Time   Address         Interface
192.168.1.1       1   FULL/BDR        00:00:35    10.0.1.1        Gi0/0
192.168.1.2       1   INIT/--         00:00:00    10.0.2.1        Gi0/1
192.168.1.3       1   2WAY/--         00:00:30    10.0.3.1        Gi0/2
"""
        neighbors = OSPFParser.parse_show_ip_ospf_neighbor(output)

        assert len(neighbors) == 3
        assert neighbors[0].state == NeighborState.FULL
        assert neighbors[1].state == NeighborState.INIT
        assert neighbors[2].state == NeighborState.TWO_WAY


class TestOSPFReasoner:
    """Test OSPF protocol reasoner."""

    def test_diagnose_exstart_area_mismatch(self):
        """Test diagnosis of EXSTART due to area mismatch."""
        from diagnostics.parsers.ospf import OSPFNeighbor, OSPFInterface, OSPFConfig

        # Setup: EXSTART neighbor
        neighbors = [
            OSPFNeighbor(
                neighbor_id="192.168.1.1",
                state=NeighborState.EXSTART,
                address="10.0.1.1",
                interface="Gi0/0",
            )
        ]

        # Setup: OSPF interface in area 0
        interfaces = {
            "Gi0/0": OSPFInterface(
                name="Gi0/0",
                ip_address="10.0.1.2/24",
                area="0",
                network_type=NetworkType.BROADCAST,
                mtu=1500,
                state="UP",
            )
        }

        config = OSPFConfig(router_id="192.168.99.1", process_id=1)

        reasoner = OSPFReasoner()
        result = reasoner.diagnose(
            neighbors=neighbors,
            interfaces=interfaces,
            config=config,
            problem_statement="OSPF stuck in EXSTART",
        )

        # Verify diagnosis
        assert result.primary_cause is not None
        assert result.primary_cause.cause == RootCauseCategory.AREA_MISMATCH
        assert result.confidence >= 0.80
        assert "area" in result.primary_cause.description.lower()


class TestDiagnosticPipeline:
    """Test end-to-end diagnostic pipeline."""

    def test_diagnose_ospf_exstart(self):
        """Test end-to-end OSPF EXSTART diagnosis."""
        pipeline = DiagnosticPipeline()

        show_commands = {
            "show ip ospf neighbor": """Neighbor ID     Pri   State           Dead Time   Address         Interface
192.168.1.1       1   EXSTART/--      00:00:00    10.0.1.1        Gi0/0
""",
            "show ip ospf interface": """Gi0/0 is up, line protocol is up
  Internet Address 10.0.1.2/24, Area 0, Attached via Interface Enable
  Process ID 1, Router ID 192.168.99.1, Network Type BROADCAST, Cost: 1
  Hello interval 10 sec, Dead interval 40 sec
""",
        }

        input_data = DiagnosticInput(
            problem_statement="OSPF stuck in EXSTART",
            show_commands=show_commands,
            protocol="ospf",
            vendor="cisco",
        )

        result = pipeline.diagnose(input_data)

        # Verify result
        assert result is not None
        assert result.confidence >= 0.75
        assert "area" in result.root_cause.lower()
        assert len(result.verification_commands) > 0
        assert result.recommended_fix is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
