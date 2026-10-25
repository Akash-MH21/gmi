# Changelog

All notable changes to gmi are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
From 1.0.0 the documented commands follow [Semantic Versioning](https://semver.org/).
Areas listed as not verified are excluded from that promise.

## [1.0.0] - 2026-10-25

### Added

#### Session and chat

- Interactive terminal session with streaming Markdown replies, model selection,
  system prompts, saved conversations and usage totals.
- Scriptable chat, model search, login and configuration commands with JSON output.
- Live model discovery with context sizes and prices from the API.

#### Media

- Image, video and audio generation from the session or shell.
- Live catalogue filtering for usable models, parameter validation, prices,
  request polling and artifact downloads.

#### API commands

- Commands generated from the four vendored GMI OpenAPI specs.
- Dry runs with masked credentials and confirmation for non-GET requests.
- `gmi api check` for GET probes with documented skips for missing parameters.

#### Sandbox and serve

- Sandbox templates, creation, exec, file transfer, timeout changes and deletion.
- One-shot sandbox runs that attempt cleanup and keep the reusable template.
- `gmi serve` HTTP chat service with a health endpoint and optional bearer token.
- Docker image built and run locally; sandbox commands verified live by the owner
  as described in the README.

#### MCP

- `gmi mcp serve` over stdio with the optional official Python SDK.
- Generated and curated tools with read, write and destructive permission gates,
  result redaction and output limits.
- `gmi mcp tools` and `gmi mcp config` without the SDK or credentials.
- Offline SDK client tests for both protocol eras documented in the README.
  Codex live verification is limited to the two tools recorded there.

#### Packaging

- Python 3.10 or newer with pip, pipx and uv installation options.

### Not verified

- Claude Code and Cursor MCP setups have not been run here.
- Streamable HTTP transport, MCP resources and MCP prompts are not implemented.
- `gmi serve` has not been deployed on the AgentBox marketplace. The Docker image
  has only been built and run locally. Image push, GMI injecting the runtime key
  and the marketplace wizard steps have not been done; gateway access control
  remains unverified.
- Cluster write operations remain unverified.
- macOS and Windows have not been tested.
