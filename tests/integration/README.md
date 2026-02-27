# Alpha Integration Tests

End-to-end test suite that exercises Alpha via filedrop messaging.

## How It Works

1. Test script sends a filedrop message to Alpha with an instruction
2. Alpha picks it up (polls every ~30s), processes via LLM, replies
3. Script polls the TestRunner inbox for a response
4. Response is validated against expected patterns

## Prerequisites

- `filedrop` CLI in PATH
- `jq` installed
- Alpha running and processing filedrop messages
- TestRunner inbox exists: `/olymp/filedrop/TestRunner/inbox/`

## Usage

```bash
# Run all tests
./test_alpha.sh

# Run specific tests
./test_alpha.sh ping exec identity

# List available tests
./test_alpha.sh --list

# Custom timeout (default: 120s)
./test_alpha.sh --timeout 90

# Save report to file
./test_alpha.sh --report /tmp/alpha-report.md

# Combine options
./test_alpha.sh --timeout 180 --report report.md ping echo exec
```

## Test Cases

| Test | Description | Validates |
|------|-------------|-----------|
| `ping` | Reply with PONG | Basic liveness |
| `echo` | Repeat a specific word | Instruction following |
| `identity` | What is your name? | Identity awareness |
| `exec` | Run a shell command | Exec tool |
| `file_read` | Read a test file | File access |
| `file_write` | Write to a file | File creation |
| `filedrop_reply` | Send a filedrop message back | Filedrop send capability |

## Exit Codes

- `0` — all tests passed
- `1` — one or more tests failed or timed out
- `2` — script error (missing prereqs, bad args)

## Notes

- Alpha uses `qwen2.5:3b` — responses are LLM-generated, not deterministic
- Default timeout is 120s (30s polling + LLM processing time)
- Tests use `TestRunner` filedrop identity to avoid polluting real inboxes
- Temporary files are created at `/tmp/test_alpha_*` and cleaned up after tests
