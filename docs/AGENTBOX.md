# AgentBox and the gmi service

Day 4 adds sandbox commands and a small HTTP chat service. All new tests are
offline. Control plane schemas come from `specs/sandbox_api.yaml` with the live
findings supplied by the project owner on 22 October 2026. These commands have
not been run against the live service during this build. The data plane is
**unverified live**. No marketplace publication has happened.

## Sandbox credentials and data centres

The control plane is `https://console.gmicloud.ai/api/v2`. It requires a console
API key with compute scope in `Authorization: Bearer ...`. Use
`GMI_COMPUTE_API_KEY` or its alias `GMI_SANDBOX_API_KEY`. The shared Day 3
resolver also supports explicit `--api-key`, `GMI_TOKEN` and the normal key
fallback. An inference key with scope `ie_model` cannot authorize sandbox
operations. A missing key or a 401 or 403 response includes the compute key hint.

Data plane calls use `https://{sandbox_key}.{domain}` with `X-Access-Token`, never
the compute bearer key. Each exec or file operation calls `/connect` first and
uses its fresh host and sandbox token. Tokens are kept only in memory.

IDC selection is `--idc-name`, then `GMI_SANDBOX_IDC_NAME`, then
`gmi config set sandbox_idc NAME`. With none set the field is omitted so creation
can use the organization's default. The catalog may require an explicit IDC:
use one for `products`. If catalog lookup rejects an omitted IDC during creation,
gmi prints the general billing explanation and still lets creation use the
organization default.

The owner verified `us-central-iowa16` and `us-central-iowa2` for this organization.
The docs example `gmi-sandbox-us` does not exist. In `us-central-iowa16`,
`gmi.sandbox.small`, `gmi.sandbox.medium` and `gmi.sandbox.large` were active.
The x-small and x-large products were unavailable. Availability can change.
Custom resources are temporarily disabled by the platform and are not offered.

```sh
# Set the compute key in your environment privately first.
gmi sandbox products --idc-name us-central-iowa16
gmi config set sandbox_idc us-central-iowa16

gmi sandbox templates create --name demo --image ubuntu:24.04 \
  --product gmi.sandbox.small --cmd 'mkdir -p /home/user' \
  --start-cmd 'sleep infinity' --wait --timeout 600 --yes
gmi sandbox templates list --json
gmi sandbox templates get TEMPLATE_ID
gmi sandbox templates logs TEMPLATE_ID

gmi sandbox create TEMPLATE_ID --timeout 300 --env APP_ENV=demo --wait --yes
gmi sandbox list --state running --json
gmi sandbox get SANDBOX_ID
gmi sandbox timeout SANDBOX_ID 900 --yes
gmi sandbox exec SANDBOX_ID -- sh -c 'printf "hello\n"'
gmi sandbox put SANDBOX_ID ./input.txt /home/user/input.txt
gmi sandbox get-file SANDBOX_ID /home/user/input.txt --out ./output.txt
gmi sandbox kill SANDBOX_ID --yes
gmi sandbox templates delete TEMPLATE_ID --yes

gmi sandbox run --image ubuntu:24.04 --yes -- uname -a
```

These are usage examples, not a record of live execution. The image must contain
the command you ask to run. Choose an appropriate image or add build commands
when creating a template.
All leaf commands accept `--json`. Creation, lifetime changes and deletion require
confirmation. Without a terminal or with `--json`, supply `--yes`.
File commands support `--username`; some IDCs ignore it so it is not a permission
isolation mechanism. Remote file paths must be absolute and their parent must
exist. Without `--out`, downloads use the remote file's basename locally.

Template waits poll every five seconds, stop on `ready` or `error` and default to
a 600 second deadline. On build error, gmi fetches the build failure message.
Sandbox `--timeout` sets the lifetime, not the wait deadline. `--wait-timeout`
sets the create wait deadline and defaults to 600 seconds. Creation prints the
sandbox ID and the service's `end_at`; it does not invent an expiry time.

Creation output masks sandbox access and traffic tokens by default, including
JSON. Only `sandbox create --show-token` reveals those tokens once with a secret
warning on stderr. Avoid that option in logs or shared terminals. Known control
and data plane credentials are redacted from other output, including exec output.
Keys are never printed. Build logs and command output may contain other private
data supplied by your workloads, so handle them privately.

Before a billable creation, gmi prints catalog price fields if present. Otherwise
it says billing is per second of runtime and covered by account credits where
applicable. It does not invent a rate, currency or price unit. The `products`
table has SKU, status, vCPU and memory in MB. It adds a price column only when the
response contains a price field.

`run` uses a deterministic template name for the image and product. It reuses a
ready template only after checking its build's image and product. Otherwise it
builds a template, creates a sandbox, waits for `running`, executes the command
and attempts to kill the sandbox in a `finally` block, including on Ctrl+C.
Templates remain for reuse. If sandbox cleanup fails, gmi reports the ID and the
manual kill command. Standalone `create` retains the resource on a wait timeout;
inspect it and kill it when finished. Exec prints stdout and stderr and returns
the command's exit code. Pending executions are polled until terminal with a
600 second deadline. A standalone exec timeout does not cancel the remote job.

## Known platform billing deletion

The owner observed every sandbox being deleted by the platform about one second
after creation. The state became `deleting` then `deleted` with:

```text
code: Sandbox.BillingNoPermission
initiator: billing
message: Deleted by the platform: billing order could not be created because the organization is not permitted to purchase this product
```

This is not a gmi error. gmi stops on the first response showing deletion, prints
the service's message with its code and initiator and exits non-zero. It does not
keep polling a deleted sandbox. The offline regression test proves this with one
detail poll. The organization needs its purchase permission resolved with GMI
before a live data plane test can proceed. This build did not request or obtain
a compute key.

## HTTP service

`gmi serve` listens on `0.0.0.0:$PORT`, default 8080. It has two routes:

| Route | Request | Response |
|---|---|---|
| `GET /health` | No body or authentication required | `200 {"status":"ok"}` |
| `POST /chat` | `{"message":"Hello","model":"optional/model"}` | `{"model":"...","reply":"...","usage":{...}}` |

| Variable | Meaning |
|---|---|
| `PORT` | Listening port, default 8080. `--port` overrides it. |
| `GMI_MAAS_BASE_URL` | Runtime MaaS base URL injected by GMI. gmi appends `/v1` if absent. Local default: `https://api.gmi-serving.com`. |
| `GMI_MAAS_API_KEY` | Runtime MaaS key injected by GMI. Used only on the upstream request. |
| `GMI_API_KEY` | Local fallback when `GMI_MAAS_API_KEY` is absent. |
| `GMI_MODELS` | Default models as a comma-separated list, whitespace-separated list or JSON array. The first model is the default. |
| `GMI_SERVE_TOKEN` | Optional service bearer token. Every route except `/health` requires it when set. |

The request model overrides `GMI_MODELS`. Without either, the default is
`openai/gpt-6.1-sol`. No model allowlist is hard-coded. Select models available to
your MaaS account. The service makes non-streaming OpenAI-compatible requests to
`/v1/chat/completions` with a 30 second upstream timeout.

**Without `GMI_SERVE_TOKEN`, the service is open to anyone who can reach it.**
Those callers can make model calls billed to the configured account. The
AgentBox gateway's own access control is unverified here. Set a service token
when exposing the service and pass it as `Authorization: Bearer <token>` from
your client. Keep all keys and tokens in runtime secrets, never in the image.
`/health` checks the process only; it does not verify MaaS credentials or access.

```sh
# With runtime secrets already set privately:
gmi serve
curl http://localhost:8080/health
# This example uses the open local service. With a service token, add its bearer header.
curl http://localhost:8080/chat -H 'Content-Type: application/json' \
  -d '{"message":"Say hello","model":"openai/gpt-6.1-sol"}'
```

Invalid JSON or invalid fields return 400. Bodies above 64 KB return 413. Missing
upstream credentials return 503. Upstream HTTP errors, network failures, invalid
responses and timeouts return 502 with a short message. Raw upstream errors and
credentials are never returned. Requests are not logged.

## Build and publish an image

The Dockerfile installs the project on slim Python, runs as a non-root user and
exposes port 8080. Its health check calls `/health`. It starts `gmi serve`.
The build context excludes local config, environment files and repository history.

Run these steps yourself with a registry you control:

```sh
docker build -t YOUR_REGISTRY/gmi-agentbox:day4 .
docker push YOUR_REGISTRY/gmi-agentbox:day4
```

Neither command was run in this build. No registry credentials are available.
For a local container test, pass secrets through the runtime environment:

```sh
docker run --rm -p 8080:8080 \
  -e GMI_API_KEY -e GMI_SERVE_TOKEN \
  YOUR_REGISTRY/gmi-agentbox:day4
```

## Marketplace wizard: five steps

The following values are a registration guide. The wizard and its current field
labels have not been exercised here. Use the image you pushed and review each
step in the console before submitting.

| Step | Values to enter |
|---|---|
| 1. Agent details | Name: `gmi`. Description: `Chat with GMI Cloud models through a small HTTP service.` |
| 2. Container image | Image: `YOUR_REGISTRY/gmi-agentbox:day4`. Startup command: image default `gmi serve`. |
| 3. Networking | Container port: `8080`. Public HTTPS port: `443`. Health path: `/health`. Chat path: `/chat`. |
| 4. MaaS integration | Enable MaaS integration. Let GMI inject `GMI_MAAS_BASE_URL` and `GMI_MAAS_API_KEY`. Models: start with `openai/gpt-6.1-sol` if available to the account. Set `GMI_MODELS` to that model or your selected list. Set `GMI_SERVE_TOKEN` as a runtime secret. |
| 5. Review and submit | Check name, description, image, port mapping, MaaS integration and selected models. Test `/health` and an authenticated `/chat` after deployment. Request the Verified path only after live validation and GMI review. |

Choose the **Verified** path for an agent hosted on AgentBox with MaaS integration,
subject to GMI's review and current program requirements. This repository does
not claim that badge or a marketplace listing.

The alternative is a self-hosted **Powered by GMI MaaS** integration: run this
image on infrastructure you operate, set the MaaS base URL, key and models and
secure access with `GMI_SERVE_TOKEN`. GMI's review and branding approval are
external steps for that path too. Hosting this service yourself does not make it
an AgentBox Verified agent.

## Verification limits

Offline tests exercise HTTP contracts, auth separation, platform deletion,
build failures, token masking, confirmations, IDC precedence, command exit codes
and cleanup after command failure or Ctrl+C. Local fake-upstream tests exercise
`/health`, `/chat`, service auth, JSON validation, request size limits, credential
redaction and upstream failures. They inspect the configured timeout without
waiting 30 seconds.

Live sandbox creation by this CLI, exec, file transfer, one-shot runs, service
deployment, Docker build and runtime, registry push, marketplace submission,
MaaS injection, gateway access control and Verified approval remain unverified.
The data plane is unverified live because billing deleted the owner's sandboxes
before it could be reached. No new live calls were made in this build.

```sh
.venv/bin/pytest -q -m 'not live and not live_media'
.venv/bin/python tools/gen_api.py --check
```
