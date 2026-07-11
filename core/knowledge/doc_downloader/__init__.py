"""
core/knowledge/doc_downloader
==============================
Populates pdf_downloads/<vendor>/<doc_type>/ with real vendor documentation,
using ONLY legitimate access paths per source:

  - versa_source.py:        docs.versa-networks.com publishes a permissive
                            robots.txt (explicit Crawl-delay, a sitemap, and
                            an Allow rule for its own file-attachment
                            endpoint) — genuinely open to respectful
                            automated access. Each page's own built-in
                            "Save as PDF" export link is used to fetch a
                            real PDF; nothing is scraped that the site
                            doesn't already offer as a direct download.

  - cisco_devnet_source.py: cisco.com and arubanetworking.hpe.com both
                            returned HTTP 403 on the very first request
                            during evaluation — including on their own
                            robots.txt — meaning their edge/WAF actively
                            blocks non-browser automated access. Rather
                            than defeat that (fake browser fingerprints,
                            proxies, stealth headless browsing), Cisco
                            content here comes exclusively through Cisco's
                            own free, official DevNet Content Search MCP
                            (core.knowledge.mcp.devnet_content_source),
                            already wired into this codebase — no scraping
                            involved. Its real coverage is Meraki and
                            Catalyst Center APIs specifically, not classic
                            IOS/OSPF/BGP CLI docs (see that module's own
                            docstring) — narrower than "all Cisco docs",
                            but genuine.

Aruba and every other vendor are deliberately NOT included yet: no
similar official, scraping-free channel has been identified for them.
"""
