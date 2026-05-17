# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.0.0-beta1 (current) | ✅ |
| < 1.0.0-beta1 | ❌ |

Only the latest released version receives security fixes. Pre-release versions (`betaN`, `rcN`) are supported until the stable release supersedes them.

---

## Reporting a Vulnerability

**Please do not open a public GitHub Issue for security vulnerabilities.**

Report vulnerabilities privately via email:

**security contact:** notenki.toclient@gmail.com

Include in your report:
- A description of the vulnerability and its potential impact
- Steps to reproduce (minimal reproduction case preferred)
- Affected version(s) and Python version
- Whether you have a proposed fix

### Response Timeline

| Step | Target |
|------|--------|
| Acknowledgement | Within 3 business days |
| Initial assessment | Within 7 days |
| Fix or mitigation | Within 30 days for critical / 90 days for others |
| Public disclosure | After fix is released |

We follow coordinated disclosure. If you intend to publish research, please contact us first so we can coordinate timing.

---

## Security Model

AgentPass provides a **four-layer defense** for M2M (machine-to-machine) authentication:

| Layer | Mechanism | Protects Against |
|-------|-----------|-----------------|
| **Ed25519 signature** | JWT signed with agent's private key; public key fetched from `agentpass.json` | Token forgery / impersonation |
| **Tamper detection** | JWT three-part structure; any 1-byte change fails verification | Man-in-the-middle modification |
| **`aud` destination lock** | `aud` claim contains full URL; verified against incoming request URL | Token relay attacks |
| **`jti` one-time use** | `AnomalyDetector` records JTI with TTL; reuse immediately rejected | Replay attacks |

Additional built-in defenses:
- **SSRF protection** — `AgentPassCrawler` resolves DNS and rejects private/loopback/link-local addresses before fetching `agentpass.json`
- **1 MB stream limit** — oversized `agentpass.json` responses are truncated and rejected
- **TTL cache** — `agentpass.json` is cached for 3600 seconds to reduce crawl surface

### What AgentPass Does NOT Protect Against

- Compromise of an agent's **private key** at rest — key storage security is the deployer's responsibility
- **Network-level attacks** (DDoS, BGP hijacking) — out of scope for a middleware library
- **Application-layer logic bugs** in the merchant code that uses AgentPass as a dependency
- **Side-channel attacks** on the Ed25519 implementation — we delegate to the `cryptography` library (pyca/cryptography)

### Scope of the `agentpass` Package

The `agentpass` public API (`from agentpass import ...`) is in scope for security reports.

The `agentpass.sandbox` subpackage (`src/agentpass/sandbox/`) is **experimental / not production-ready**. Findings there are welcome but lower priority.

---

## Dependency Security

AgentPass depends on the following security-sensitive libraries:

| Library | Role | Minimum Version |
|---------|------|----------------|
| `cryptography` | Ed25519 key generation and signature verification | >= 44 |
| `PyJWT[crypto]` | JWT encoding/decoding | >= 2.10 |
| `httpx` | Async HTTP for `agentpass.json` fetch | >= 0.28 |

If a CVE is published for any of these dependencies, please report it to us and we will release a version with updated constraints promptly.

---

## Python Version Policy

AgentPass requires **Python >= 3.13**. We test against Python 3.14 in CI. If a Python version security release introduces incompatibilities, we will address them as high-priority issues.

---

## Acknowledgements

We are grateful to security researchers who responsibly disclose vulnerabilities. With your permission, we will acknowledge your contribution in the release notes for the fix.
