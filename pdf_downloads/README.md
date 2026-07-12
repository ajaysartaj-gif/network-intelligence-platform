# pdf_downloads/

Real vendor documentation, organized `<vendor>/<doc_type>/`, populated by
`core/knowledge/doc_downloader/`.

```
pdf_downloads/
  cisco/            configuration | troubleshooting | white_paper | data_sheet | command_reference
  versa/            configuration | troubleshooting | white_paper | data_sheet | command_reference
  fortinet/         configuration | troubleshooting | white_paper | data_sheet | command_reference
  paloalto/         configuration | troubleshooting | white_paper | data_sheet | command_reference
  rfc/              flat — RFCs are vendor-neutral protocol standards, not one OEM's doc type
```

## Run it

```
python3 -m core.knowledge.doc_downloader.run
```

Options: `--versa-limit N` / `--fortinet-limit N` / `--paloalto-limit N`
(all default 20 — bounded on purpose, see below), `--skip-versa` /
`--skip-cisco` / `--skip-fortinet` / `--skip-paloalto` / `--skip-rfc`,
`--out <dir>`.

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
  community site returns 403. (Its actual *developer docs* live at a
  different, genuinely open domain — see `paloalto/` below.)
- `support.checkpoint.com`'s `robots.txt` says `Allow: /` for everyone,
  but its actual download endpoints return `x-amzn-waf-action: challenge`
  — an active AWS WAF bot-challenge sitting underneath a permissive-looking
  robots file.
- `devhub.arubanetworks.com` (HPE's shared Aruba + Juniper developer hub,
  post-acquisition) has no robots restriction and no 403, but is a
  client-side-rendered Next.js app — the raw HTML is just an empty shell
  with no sitemap to enumerate. Real, but needs a headless browser to
  render, which this project doesn't build.

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

**paloalto/** — `pan.dev`, Palo Alto's actual developer-docs site
(Docusaurus-based) — a different domain from the marketing site and
LIVEcommunity that both block automation. No `robots.txt` at all (404 —
the standard "no restrictions declared" case), a real public sitemap, and
genuine static per-page content confirmed directly in an `<article>`
element (the page even offers a "Copy contents as Markdown for AI usage"
button). No PDF export exists here, so content is saved as markdown, same
honest labeling as `cisco/`. Narrowed by default to network-security/
firewall-relevant sitemap paths (`/swfw/`, `/access/`, `/terraform/panos/`)
rather than pulling in every SDK/Terraform-provider page indiscriminately.

**rfc/** — `rfc-editor.org` is IETF's public archive; no evaluation
needed the way the vendor sites required. Reuses the already-existing
`core.knowledge.fetchers.rfc_fetcher.fetch_rfc_text()`. Curated for this
tool's actual protocol coverage (OSPF, BGP, VRRP/HSRP-adjacent, EIGRP,
IS-IS, RIP, MPLS/L3VPN/EVPN/VXLAN, plus the foundational L2/L3 specs those
depend on) rather than attempting to mirror the whole RFC series. Flat,
not vendor-nested — an RFC is a protocol standard, not one OEM's document.

**Aruba, Juniper, Arista, Check Point**: deliberately not included. No
legitimate, scraping-free channel has been found for any of them yet
(Aruba/Juniper's shared devhub exists but needs JS rendering — see above).
Add one the same way — a `<vendor>_source.py` with a
`run(out_root) -> dict` function — only once one exists.

## This corpus actually gets used, not just downloaded

Downloading real documents was only half the job. `core.knowledge.
enterprise.pipelines.ensure_pdf_downloads_ingested()` (wired into
`IntentEngine._rag_context_for()`, called on every troubleshooting
request) ingests this whole tree into the SAME RAG store live sessions
query — before that bridge existed, this was real content sitting on
disk with nothing reading it, the exact gap `corpus/general/*.txt` had
before `ensure_general_corpus_ingested()`. Files over
`core.knowledge.parsers.MAX_FILE_SIZE_BYTES` (15MB — e.g. Fortinet's
3,468-page consolidated FortiOS guide) are skipped rather than parsed,
logged clearly, never silently hung on.

What a live session does with it once retrieved: `core.troubleshooting.
reasoning.Reasoner.synthesize_answer()` turns multiple real retrieved
hits into one short, inline-cited answer — the same shape as a search
engine's own AI-overview answer (one synthesized paragraph citing
"Cisco Systems +2", not a bare source list) — surfaced as a
"🔎 Synthesized Answer" section in the troubleshooting report,
`session.synthesized_answer`. Never fabricated: empty when nothing real
was actually retrieved that session.

## Idempotency

`.manifest.json` (gitignored, regenerates on first run) tracks every
source URL already fetched, keyed by URL with a content sha256. Re-running
is always safe — already-downloaded documents are skipped, never
re-fetched or re-requested.
