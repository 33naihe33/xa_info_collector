# Official Image DNS Handling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permit image downloads from configured official domains when this network resolves them to a reserved address, without weakening redirect SSRF protection.

**Architecture:** The initial image URL is protected by the configured hostname allowlist. DNS address classification is retained for redirect destinations, which remain an SSRF boundary. A database backfill invokes the existing download and validation pipeline for image-empty official documents.

**Tech Stack:** Python 3.12, pytest, httpx, Pillow, SQLite.

## Global Constraints

- Only `http` and `https` image URLs are accepted.
- An initial image hostname must be in the configured allowlist.
- Redirect destinations must remain allowlisted and reject private, loopback, link-local, and reserved addresses.
- Image size and magic validation remain unchanged.

---

### Task 1: Test and implement initial official-domain handling

**Files:**
- Modify: `tests/collector/test_h05_image_security.py`
- Modify: `collector/base.py`

**Interfaces:**
- Consumes: `BaseAdapter._stream_download_image(url, max_size, allowed_domains)`.
- Produces: initial allowlisted URLs can be downloaded despite a locally rewritten reserved DNS result; redirects remain protected.

- [ ] **Step 1: Write the failing test**

```python
def test_image_allowlisted_initial_host_accepts_reserved_dns(monkeypatch):
    adapter = _make_adapter()
    monkeypatch.setattr("socket.gethostbyname", lambda _host: "198.18.2.10")
    # mock a valid HEAD and stream response, then assert non-None bytes
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/collector/test_h05_image_security.py::test_image_allowlisted_initial_host_accepts_reserved_dns -v`

Expected: FAIL because the initial URL is rejected as reserved.

- [ ] **Step 3: Write minimal implementation**

```python
# _validate_host(u, validate_resolved_ip=True)
# initial invocation passes False; redirect invocations keep the default True.
```

- [ ] **Step 4: Run focused image-security tests**

Run: `pytest tests/collector/test_h05_image_security.py -v`

Expected: PASS, including the existing private-redirect rejection test.

### Task 2: Backfill images for existing official documents

**Files:**
- No production file changes; run a one-off, idempotent database backfill.

**Interfaces:**
- Consumes: `XionganPortalAdapter.fetch_detail()` and `download_images()`.
- Produces: successful local image paths stored in `documents.images`; failures remain `[]`.

- [ ] **Step 1: Run a backfill limited to `xiongan_portal` records with `images = '[]'`**

For each record, fetch the source page, call the existing image extractor and downloader, and update only its `images` column.

- [ ] **Step 2: Verify persisted image paths and files**

Run a read-only SQLite query for non-empty image arrays and count the corresponding local files.
