# Cobot Release Plan

## Overview

This document outlines the release process for Cobot, including manual steps for v0.1.0 and automation for future releases.

## Release Artifacts

| Artifact | Format | Distribution |
|----------|--------|--------------|
| Source tarball | `.tar.gz` | GitHub Releases |
| Python wheel | `.whl` | PyPI + GitHub Releases |
| Docker image | `ghcr.io/ultanio/cobot` | GitHub Container Registry |
| Checksums | `SHA256SUMS` | GitHub Releases |
| Nostr signature | `SHA256SUMS.sig` | GitHub Releases (npub signed) |

---

## Phase 1: Manual v0.1.0 Release

### Tasks

| # | Task | Owner | Status |
|---|------|-------|--------|
| 1.1 | Create git tag `v0.1.0` | 🦊 Doxios | |
| 1.2 | Build source tarball | 🦊 Doxios | |
| 1.3 | Build Python wheel | 🦊 Doxios | |
| 1.4 | Generate SHA256SUMS | 🦊 Doxios | |
| 1.5 | Create GitHub Release (draft) | 🦊 Doxios | |
| 1.6 | Upload artifacts to release | 🦊 Doxios | |
| 1.7 | **Sign SHA256SUMS with npub** | 👤 k9ert | |
| 1.8 | Upload signature to release | 🦊 Doxios | |
| 1.9 | Publish release (mark experimental) | 🦊 Doxios | |

### Release Notes Template (v0.1.0)

```markdown
# Cobot v0.1.0 (Experimental)

⚠️ **This is an experimental release. Not recommended for production use.**

## Known Security Issues

- **Pairing codes are not encrypted** - codes are stored in plaintext in `~/.cobot/pairing.yml`
- **No rate limiting** - pairing requests are not rate-limited
- **exec plugin enabled by default** - allows shell command execution

## Features

- Plugin architecture with 19 built-in plugins
- Telegram integration with long polling
- User authorization via pairing codes
- PPQ and Ollama LLM providers
- Setup wizard (`cobot wizard init`)
- Async architecture for non-blocking I/O

## Installation

```bash
pip install cobot[telegram]
cobot wizard init
cobot run
```

## Checksums

See `SHA256SUMS` for file checksums.
Verify signature: `SHA256SUMS.sig` (signed with npub1...)

## Full Changelog

https://github.com/ultanio/cobot/commits/v0.1.0
```

---

## Phase 2: Release Automation

### 2.1 Conventional Commits

Enforce commit message format for automatic changelog generation.

**Format:**
```
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

**Types:**
- `feat:` - New feature (MINOR version bump)
- `fix:` - Bug fix (PATCH version bump)
- `docs:` - Documentation only
- `style:` - Formatting, no code change
- `refactor:` - Code change, no feature/fix
- `perf:` - Performance improvement
- `test:` - Adding tests
- `chore:` - Maintenance

**Breaking Changes:**
- `feat!:` or `fix!:` - Breaking change (MAJOR version bump)
- Or add `BREAKING CHANGE:` in footer

### Tasks

| # | Task | Owner | Status |
|---|------|-------|--------|
| 2.1.1 | Add commitlint config | 🦊 Doxios | |
| 2.1.2 | Add pre-commit hook for commit messages | 🦊 Doxios | |
| 2.1.3 | Document commit conventions in CONTRIBUTING.md | 🦊 Doxios | |

---

### 2.2 GitHub Actions: Release Workflow

**Trigger:** Push tag `v*` (e.g., `v0.2.0`)

**Jobs:**

```yaml
release:
  jobs:
    build:
      - Checkout code
      - Build source tarball
      - Build Python wheel
      - Upload artifacts

    docker:
      - Build Docker image
      - Push to ghcr.io/ultanio/cobot:$TAG
      - Push to ghcr.io/ultanio/cobot:latest

    checksums:
      - Download all artifacts
      - Generate SHA256SUMS
      - Upload SHA256SUMS

    sign:
      - Download SHA256SUMS
      - Sign with npub (requires secret)
      - Upload SHA256SUMS.sig

    pypi:
      - Download wheel
      - Publish to PyPI (requires secret)

    release:
      - Generate changelog from commits
      - Create GitHub Release
      - Upload all artifacts
```

### Tasks

| # | Task | Owner | Status |
|---|------|-------|--------|
| 2.2.1 | Create `.github/workflows/release.yml` | 🦊 Doxios | |
| 2.2.2 | **Set up PyPI API token** | 👤 k9ert | |
| 2.2.3 | **Add PYPI_TOKEN to GitHub secrets** | 👤 k9ert | |
| 2.2.4 | Test workflow with `v0.1.1-rc1` tag | 🦊 Doxios | |

---

### 2.3 Docker Image

**Dockerfile:**

```dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY . .
RUN pip install -e ".[telegram]"

# Default config location
ENV COBOT_CONFIG=/config/cobot.yml

ENTRYPOINT ["cobot"]
CMD ["run"]
```

**Tags:**
- `ghcr.io/ultanio/cobot:v0.1.0` - Specific version
- `ghcr.io/ultanio/cobot:latest` - Latest stable
- `ghcr.io/ultanio/cobot:main` - Latest main branch (for dev)

### Tasks

| # | Task | Owner | Status |
|---|------|-------|--------|
| 2.3.1 | Create `Dockerfile` | 🦊 Doxios | |
| 2.3.2 | Create `.dockerignore` | 🦊 Doxios | |
| 2.3.3 | Add Docker build to release workflow | 🦊 Doxios | |
| 2.3.4 | **Enable GitHub Container Registry** | 👤 k9ert | |

---

### 2.4 PyPI Publishing

**Package name:** `cobot`

**Extras:**
- `cobot[telegram]` - With Telegram support
- `cobot[nostr]` - With Nostr support  
- `cobot[all]` - Everything

### Tasks

| # | Task | Owner | Status |
|---|------|-------|--------|
| 2.4.1 | **Register `cobot` on PyPI** | 👤 k9ert | |
| 2.4.2 | **Create PyPI API token** | 👤 k9ert | |
| 2.4.3 | Add PyPI publish to release workflow | 🦊 Doxios | |
| 2.4.4 | Test with TestPyPI first | 🦊 Doxios | |

---

### 2.5 Nostr Signing

Sign `SHA256SUMS` with the project's npub for verification.

**Signing process:**
1. Generate SHA256SUMS of all artifacts
2. Sign with Nostr private key (nsec)
3. Output signature file (Schnorr signature)

**Verification:**
```bash
# Users can verify with npub
cobot verify-release v0.1.0
```

### Tasks

| # | Task | Owner | Status |
|---|------|-------|--------|
| 2.5.1 | **Create dedicated npub for releases** | 👤 k9ert | |
| 2.5.2 | **Add NOSTR_NSEC to GitHub secrets** | 👤 k9ert | |
| 2.5.3 | Create signing script | 🦊 Doxios | |
| 2.5.4 | Add signing to release workflow | 🦊 Doxios | |
| 2.5.5 | Document verification process | 🦊 Doxios | |

---

### 2.6 Changelog Generation

Use [git-cliff](https://github.com/orhun/git-cliff) or similar for automatic changelog.

**Output:** `CHANGELOG.md` updated on each release

**Format:**
```markdown
## [0.2.0] - 2026-02-15

### Features
- feat: add cool thing (#123)

### Bug Fixes  
- fix: resolve issue (#124)

### Breaking Changes
- feat!: change API (#125)
```

### Tasks

| # | Task | Owner | Status |
|---|------|-------|--------|
| 2.6.1 | Add `cliff.toml` config | 🦊 Doxios | |
| 2.6.2 | Add changelog generation to release workflow | 🦊 Doxios | |
| 2.6.3 | Generate initial CHANGELOG.md | 🦊 Doxios | |

---

## Summary: What You Need To Do (👤 k9ert)

### Repository Protection (Priority)

1. **Enable branch protection on `main`** (Settings → Branches → Add rule)
   - Require pull request before merging
   - Require status checks to pass (CI)
   - Do not allow bypassing the above settings
   - *Doxios cannot do this - requires admin permissions*

### For v0.1.0 (Now)

2. **Sign SHA256SUMS with your npub** after I create the release draft

### For Automation (After v0.1.0)

2. **PyPI Setup:**
   - Register `cobot` package name on pypi.org
   - Create API token with upload permissions
   - Add `PYPI_TOKEN` to GitHub repo secrets

3. **GitHub Container Registry:**
   - Enable GHCR for ultanio org (Settings → Packages)

4. **Nostr Signing:**
   - Create dedicated npub/nsec for release signing
   - Add `NOSTR_NSEC` to GitHub repo secrets
   - Share the npub publicly for verification

---

## Execution Order

```
Phase 1: Manual v0.1.0
├── 1.1-1.6: Doxios creates release
├── 1.7: k9ert signs
└── 1.8-1.9: Doxios publishes

Phase 2: Automation  
├── 2.1: Conventional commits setup
├── 2.6: Changelog generation
├── 2.2: Release workflow (builds)
├── 2.3: Docker (k9ert enables GHCR)
├── 2.4: PyPI (k9ert sets up token)
└── 2.5: Nostr signing (k9ert creates npub)
```

---

## Files to Create

- [ ] `Dockerfile`
- [ ] `.dockerignore`
- [ ] `.github/workflows/release.yml`
- [ ] `cliff.toml` (changelog config)
- [ ] `scripts/sign-release.py`
- [ ] Update `CONTRIBUTING.md` with commit conventions
