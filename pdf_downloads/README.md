# pdf_downloads/

Real vendor documentation, organized `<vendor>/<doc_type>/`, populated by
`core/knowledge/doc_downloader/`.

```
pdf_downloads/
  cisco/            configuration | troubleshooting | white_paper | data_sheet | command_reference
  versa/            configuration | troubleshooting | white_paper | data_sheet | command_reference
  fortinet/         configuration | troubleshooting | white_paper | data_sheet | command_reference
  rfc/              flat — RFCs are vendor-neutral protocol standards, not one OEM's doc type
```

## Run it

```
python3 -m core.knowledge.doc_downloader.run
```

Options: `--versa-limit N` / `--fortinet-limit N` (both default 20 —
bounded on purpose, see below), `--skip-versa` / `--skip-cisco` /
`--skip-fortinet` / `--skip-rfc`, `--out <dir>`.

## Where each source's content actually comes from — and why

Every vendor here was evaluated the same way before any code was
written: check `robots.txt`, check what an actual page returns, don't
assume. Two of the four originally-given sample sites returned **HTTP 403
on the very first request — including on their own `robots.txt`**:

- `cisco.com`
- `arubanetworking.hpe.com`

That's their edge/WAF actively blocking non-browser automated access, on
purpose. A later sweep of the remaining major OEMs found the same pattern
in different forms:

- `juniper.net`'s own `robots.txt` states outright: *"The use of robots or
  other automated means to access the Juniper site... is strictly
  prohibited"* — an explicit policy, honored regardless of the technical
  rules below it.
- `arista.com`'s `/robots.txt` returns its JS app shell, not a real robots
  file — a CSP-locked SPA, not crawlable this way regardless of policy.
- `paloaltonetworks.com` disallows its own real content paths; its
  community site returns 403.
- `support.checkpoint.com`'s `robots.txt` says `Allow: /` for everyone,
  but its actual download endpoints return `x-amzn-waf-action: challenge`
  — an active AWS WAF bot-challenge sitting underneath a permissive-looking
  robots file.

None of these are things this project works around — fake browser
fingerprints, stealth headless browsing, proxies, WAF-challenge solving.
That's deliberately defeating a vendor's own access control, not a coding
problem to route past.

**cisco/** — populated exclusively through Cisco's own free, official
[DevNet Content Search MCP](https://devnet.cisco.com/v1/foundation-search-mcp/mcp)
(`core/knowledge/mcp/devnet_content_source.py`, already used elsewhere in
this codebase's live troubleshooting path). No scraping. Real, honest
scope limit: that MCP's own coverage is Meraki and Catalyst Center APIs
specifically — not classic IOS/OSPF/BGP CLI documentation. Saved files are
markdown (the MCP returns structured API-doc fields, not a scanned PDF),
each one clearly headed with its real source.

**versa/** — `docs.versa-networks.com` publishes a genuinely permissive
`robots.txt` (explicit `Crawl-delay: 5`, a public sitemap, an `Allow` rule
for its own file-attachment endpoint). Real PDFs, fetched via each page's
own built-in "Save as PDF" export link — a feature the site offers to any
visitor, not a reconstructed or hidden URL. The crawler parses and honors
`robots.txt` itself (not assumed), sleeps the declared crawl-delay between
every request, and only ever visits URLs the sitemap itself lists.

**fortinet/** — `docs.fortinet.com`'s own `robots.txt` has no blanket
disallow for unnamed agents (`Crawl-delay: 2`, a handful of specific
archived-product exclusions). Real PDFs, confirmed directly in page HTML
as S3-hosted "Download PDF" links
(`fortinetweb.s3.amazonaws.com/docs.fortinet.com/v2/attachments/.../*.pdf`).
No sitemap exists for this subdomain, so this source seeds from each
product's own listing page (e.g. `/product/fortigate/7.4.0`) rather than
enumerating the entire catalogue.

**rfc/** — `rfc-editor.org` is IETF's public archive; no evaluation
needed the way the vendor sites required. Reuses the already-existing
`core.knowledge.fetchers.rfc_fetcher.fetch_rfc_text()`. Curated for this
tool's actual protocol coverage (OSPF, BGP, VRRP, and the foundational
specs those depend on) rather than attempting to mirror the whole RFC
series. Flat, not vendor-nested — an RFC is a protocol standard, not one
OEM's document.

**Aruba, Juniper, Arista, Palo Alto, Check Point**: deliberately not
included. No legitimate, scraping-free channel has been found for any of
them yet. Add one the same way — a `<vendor>_source.py` with a
`run(out_root) -> dict` function — only once one exists.

## Idempotency

`.manifest.json` (gitignored, regenerates on first run) tracks every
source URL already fetched, keyed by URL with a content sha256. Re-running
is always safe — already-downloaded documents are skipped, never
re-fetched or re-requested.
