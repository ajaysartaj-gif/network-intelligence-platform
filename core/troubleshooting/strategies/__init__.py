"""
core/troubleshooting/strategies
================================
Bridges between the Mismatch Investigation system (top-level knowledge/,
adapters/, strategies/ packages) and the LIVE Troubleshooting Engine runtime
(core/vendor gateway, core/knowledge RAG, core/troubleshooting session model).

Nothing in this package contains vendor or protocol logic. It only translates
between two already-existing abstractions:

  gateway_adapter.py    adapters.base.DeviceAdapter      <->  core.vendor.VendorGateway
  live_retriever.py     knowledge.rag_engine.Retriever   <->  core.knowledge.rag
  mismatch_bridge.py    orchestrates the above + converts strategies.mismatch.Finding
                        objects into core.troubleshooting.models (Hypothesis /
                        Observation / Evidence) so the rest of the engine's
                        confidence loop, fix generation and reporting is unchanged.
"""
