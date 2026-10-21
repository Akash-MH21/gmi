# API coverage (2026-10-21)

Key scope: `ie_model`; product: `IE`.

Generated 93 of 93 operations. Live run: 27. Not run: 66.

## Results

| Service | Operation | HTTP | Verdict |
|---|---|---:|---|
| cluster | `get-baremetal-products` | 401 | needs another key type |
| cluster | `list-baremetals` | 401 | needs another key type |
| cluster | `get-container-products` | 401 | needs another key type |
| cluster | `get-containers` | 401 | needs another key type |
| cluster | `get-elastic-ip-products` | 401 | needs another key type |
| cluster | `list-elastic-ip` | 401 | needs another key type |
| cluster | `list-firewalls` | 401 | needs another key type |
| cluster | `list-images` | 401 | needs another key type |
| cluster | `get-templates` | 401 | needs another key type |
| cluster | `list-vpcs` | 401 | needs another key type |
| iam | `get-user-profile` | 401 | needs another key type |
| iam | `list-ssh-keys` | 401 | needs another key type |
| iam | `verify-api-key` | 200 | ok |
| iam | `get-organization` | 401 | needs another key type |
| iam | `get-organizations-org-id-users` | 401 | needs another key type |
| iam | `list-api-keys` | 401 | needs another key type |
| idc | `list-idcs` | 200 | ok |
| sandbox | `get-sandbox` | 401 | needs another key type |
| sandbox | `list-sandboxes` | 401 | needs another key type |
| sandbox | `get-sandbox-execution` | 401 | needs another key type |
| sandbox | `download-sandbox-file` | 401 | needs another key type |
| sandbox | `get-template` | 401 | needs another key type |
| sandbox | `get-template-build` | 401 | needs another key type |
| sandbox | `get-template-build-logs` | 401 | needs another key type |
| sandbox | `list-product-catalog` | 401 | needs another key type |
| sandbox | `list-template-builds` | 401 | needs another key type |
| sandbox | `list-templates` | 401 | needs another key type |

## Summary by service

| Service | Run | Ok | Needs another key type | Not run |
|---|---:|---:|---:|---:|
| iam | 6 | 1 | 5 | 24 |
| idc | 1 | 1 | 0 | 0 |
| sandbox | 10 | 0 | 10 | 11 |
| cluster | 10 | 0 | 10 | 31 |

## Verdict totals

| Verdict | Count |
|---|---:|
| ok | 2 |
| needs another key type | 25 |
| not found | 0 |
| server error | 0 |
| network error | 0 |

## Not run

| Service | Operation | Reason |
|---|---|---|
| cluster | `create-baremetals` | not a GET |
| cluster | `delete-baremetal` | not a GET, needs a path parameter |
| cluster | `execute-baremetal-action` | not a GET, needs a path parameter |
| cluster | `get-baremetal` | needs a path parameter |
| cluster | `update-baremetal` | not a GET, needs a path parameter |
| cluster | `container-shell` | not a GET, needs a path parameter |
| cluster | `create-container` | not a GET |
| cluster | `delete-containers` | not a GET, needs a path parameter |
| cluster | `download-log` | needs a path parameter |
| cluster | `get-container` | needs a path parameter |
| cluster | `restart-container` | not a GET, needs a path parameter |
| cluster | `update-container` | not a GET, needs a path parameter |
| cluster | `allocate-elastic-ip` | not a GET |
| cluster | `associate-elastic-ip` | not a GET, needs a path parameter |
| cluster | `disassociate-elastic-ip` | not a GET, needs a path parameter |
| cluster | `get-elastic-ip` | needs a path parameter |
| cluster | `release-elastic-ip` | not a GET, needs a path parameter |
| cluster | `associate-firewall` | not a GET, needs a path parameter |
| cluster | `create-firewall` | not a GET |
| cluster | `delete-firewall` | not a GET, needs a path parameter |
| cluster | `disassociate-firewall` | not a GET, needs a path parameter |
| cluster | `get-firewall` | needs a path parameter |
| cluster | `update-firewall` | not a GET, needs a path parameter |
| cluster | `get-image` | needs a path parameter |
| cluster | `create-templates` | not a GET |
| cluster | `delete-template` | not a GET, needs a path parameter |
| cluster | `get-template` | needs a path parameter |
| cluster | `update-templates` | not a GET, needs a path parameter |
| cluster | `allocate-default-vpc` | not a GET |
| cluster | `get-vpc` | needs a path parameter |
| cluster | `release-default-vpc` | not a GET, needs a path parameter |
| iam | `accept-invitation-by-key` | not a GET, needs a path parameter |
| iam | `create-auth-token` | not a GET |
| iam | `create-auth-token-o-auth` | not a GET |
| iam | `create-session` | not a GET |
| iam | `create-ssh-key` | not a GET |
| iam | `delete-me-ssh-keys-ssh-key-id` | not a GET |
| iam | `refresh-session` | not a GET |
| iam | `resend2-fa-code` | not a GET |
| iam | `update-ssh-key` | not a GET |
| iam | `update-user-password` | not a GET |
| iam | `update-user-profile` | not a GET |
| iam | `exchange-authorization-code` | not a GET |
| iam | `accept-invitation` | not a GET, needs a path parameter |
| iam | `create-api-key` | not a GET |
| iam | `delete-api-key` | not a GET, needs a path parameter |
| iam | `delete-organization` | not a GET |
| iam | `register-organization` | not a GET |
| iam | `send-invitations-by-email` | not a GET |
| iam | `transfer-organization-owner` | not a GET |
| iam | `update-organization-info` | not a GET |
| iam | `delete-users-user-id` | not a GET |
| iam | `email-verification` | not a GET |
| iam | `request-password-reset` | not a GET |
| iam | `resend-email-code-request` | not a GET |
| sandbox | `connect-sandbox` | not a GET |
| sandbox | `create-sandbox` | not a GET |
| sandbox | `delete-sandbox` | not a GET |
| sandbox | `set-sandbox-timeout` | not a GET |
| sandbox | `update-sandbox` | not a GET |
| sandbox | `cancel-sandbox-execution` | not a GET |
| sandbox | `create-sandbox-execution` | not a GET |
| sandbox | `upload-sandbox-file` | not a GET |
| sandbox | `create-template` | not a GET |
| sandbox | `delete-template` | not a GET |
| sandbox | `update-template` | not a GET |
