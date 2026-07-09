"""Vendor-specific documentation fetchers."""
from core.knowledge.fetchers.base_fetcher import VendorFetcher
from core.knowledge.fetchers.cisco_fetcher import CiscoFetcher
from core.knowledge.fetchers.juniper_fetcher import JuniperFetcher
from core.knowledge.fetchers.arista_fetcher import AristaFetcher
from core.knowledge.fetchers.paloalto_fetcher import PaloAltoFetcher
from core.knowledge.fetchers.fortinet_fetcher import FortinetFetcher
from core.knowledge.fetchers.aruba_fetcher import ArubaFetcher
from core.knowledge.fetchers.huawei_fetcher import HuaweiFetcher
from core.knowledge.fetchers.dell_fetcher import DellFetcher
from core.knowledge.fetchers.extreme_fetcher import ExtremeFetcher
from core.knowledge.fetchers.rfc_fetcher import fetch_rfc_text

__all__ = [
    "VendorFetcher",
    "CiscoFetcher",
    "JuniperFetcher",
    "AristaFetcher",
    "PaloAltoFetcher",
    "FortinetFetcher",
    "ArubaFetcher",
    "HuaweiFetcher",
    "DellFetcher",
    "ExtremeFetcher",
    "fetch_rfc_text",
]
