# pdf_downloads/

Real vendor documentation, organized `<vendor>/<doc_type>/`, populated by
`core/knowledge/doc_downloader/`.

```
pdf_downloads/
  cisco/            configuration | troubleshooting | white_paper | data_sheet | command_reference
  versa/            configuration | troubleshooting | white_paper | data_sheet | command_reference
```

## Run it

```
python3 -m core.knowledge.doc_downloader.run
```

Options: `--versa-limit N` (default 20 — bounded on purpose, see below),
`--skip-versa`, `--skip-cisco`, `--out <dir>`.

## Where each vendor's content actually comes from — and why

Before writing any code, the four sites given as samples were checked
directly. Two returned **HTTP 403 on the very first request — including
on their own `robots.txt`**:

- `cisco.com`
- `arubanetworking.hpe.com`

That's their edge/WAF actively blocking non-browser automated access, on
purpose. Making that work would mean deliberately defeating a vendor's own
access control — fake browser fingerprints, stealth headless browsing,
proxies. This project does not do that, regardless of technical
feasibility.

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

**Aruba and every other vendor**: deliberately not included yet. No
similar official, scraping-free channel has been identified for them. Add
one the same way — a `<vendor>_source.py` with a `run(out_root) -> dict`
function — only once a legitimate access path exists.

## Idempotency

`.manifest.json` (gitignored, regenerates on first run) tracks every
source URL already fetched, keyed by URL with a content sha256. Re-running
is always safe — already-downloaded documents are skipped, never
re-fetched or re-requested.
