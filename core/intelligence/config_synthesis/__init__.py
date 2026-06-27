"""
core/intelligence/config_synthesis
==================================
Configuration Intelligence — a configuration is COMPILED from intent, not invented.

The same intent on the same platform yields the same canonical commands on every
device; values are validated (so 8.4.4.4 never reaches a router); commands are
grounded, where possible, in the vendor's own documentation; and verification is
honest — it separates "applied" from "persisted" from "operational", so a correct
config is never failed because a lab can't reach public NTP, and a Netmiko save
that aborts on prompt detection is repaired, not mistaken for a bad config.

  from core.intelligence.config_synthesis import (
      get_config_intelligence, synthesize_config, wire_configuration)

  wire_configuration()
  plan = synthesize_config("configure free dns and ntp, clock in IST",
                           devices=["R1", "R2", "R3"])
  # plan["consistent"] is True; plan["per_device"][d]["commands"] are identical.
"""
from core.intelligence.config_synthesis.engine import (
    ConfigurationIntelligence, get_config_intelligence, synthesize_config,
    wire_configuration,
)
from core.intelligence.config_synthesis.synthesizer import parse_intent, ConfigSynthesizer
from core.intelligence.config_synthesis.verification import (
    verify_plan, save_repair_directive,
)
from core.intelligence.config_synthesis.base import (
    ConfigIntent, ConfigPlan, StateCheck, CheckKind, Vendor,
)

__all__ = [
    "ConfigurationIntelligence", "get_config_intelligence", "synthesize_config",
    "wire_configuration", "parse_intent", "ConfigSynthesizer", "verify_plan",
    "save_repair_directive", "ConfigIntent", "ConfigPlan", "StateCheck",
    "CheckKind", "Vendor",
]
