#!/bin/bash
# test_alpha.sh — Integration test suite for Alpha via filedrop
#
# Sends filedrop messages to Alpha and validates responses.
# Uses a dedicated TestRunner identity to avoid polluting real inboxes.
#
# Usage:
#   ./test_alpha.sh              # run all tests
#   ./test_alpha.sh ping exec    # run specific tests
#   ./test_alpha.sh --list       # list available tests
#   ./test_alpha.sh --timeout 90 # custom timeout (default: 120s)
#   ./test_alpha.sh --report /tmp/report.md  # save report to file
#
# Prerequisites:
#   - filedrop CLI in PATH
#   - jq installed
#   - /olymp/filedrop/TestRunner/inbox/ exists
#   - Alpha is running and processing filedrop messages

set -euo pipefail

# ===========================================================================
# Configuration
# ===========================================================================

DEFAULT_TIMEOUT=120          # seconds (Alpha polls ~30s + LLM processing)
SENDER="TestRunner"          # filedrop identity for test runner
TARGET="Alpha"               # agent under test
INBOX="/olymp/filedrop/$SENDER/inbox"
POLL_INTERVAL=5              # seconds between inbox polls
PAUSE_BETWEEN=5              # seconds between tests
REPORT_FILE=""               # optional report output path

# Colors (disabled if not a terminal)
if [ -t 1 ]; then
    GREEN='\033[0;32m'
    RED='\033[0;31m'
    YELLOW='\033[1;33m'
    BLUE='\033[0;34m'
    BOLD='\033[1m'
    NC='\033[0m'
else
    GREEN='' RED='' YELLOW='' BLUE='' BOLD='' NC=''
fi

# Test results tracking
declare -a TEST_NAMES=()
declare -a TEST_RESULTS=()
declare -a TEST_DURATIONS=()
declare -a TEST_DETAILS=()
TESTS_PASSED=0
TESTS_FAILED=0
TESTS_TIMEOUT=0

# ===========================================================================
# Available tests (order matters — simpler tests first)
# ===========================================================================

ALL_TESTS=(ping echo identity exec file_read file_write filedrop_reply)

# ===========================================================================
# Core helpers
# ===========================================================================

log() {
    echo -e "${BLUE}[test]${NC} $*"
}

log_ok() {
    echo -e "${GREEN}  ✅ $*${NC}"
}

log_fail() {
    echo -e "${RED}  ❌ $*${NC}"
}

log_warn() {
    echo -e "${YELLOW}  ⚠️  $*${NC}"
}

# Check prerequisites
check_prereqs() {
    local errors=0

    if ! command -v filedrop &>/dev/null; then
        echo "ERROR: filedrop CLI not found in PATH" >&2
        errors=$((errors + 1))
    fi

    if ! command -v jq &>/dev/null; then
        echo "ERROR: jq not found in PATH" >&2
        errors=$((errors + 1))
    fi

    if [ ! -d "$INBOX" ]; then
        echo "ERROR: TestRunner inbox not found at $INBOX" >&2
        echo "  Create it: mkdir -p $INBOX" >&2
        errors=$((errors + 1))
    fi

    if [ $errors -gt 0 ]; then
        echo "$errors prerequisite(s) missing — cannot run tests" >&2
        exit 2
    fi
}

# Clear the TestRunner inbox of old messages
clear_inbox() {
    if [ -d "$INBOX" ]; then
        rm -f "$INBOX"/*.json 2>/dev/null || true
    fi
}

# Send a filedrop message to Alpha and return the send timestamp
send_message() {
    local subject="$1"
    local content="$2"
    local before_ts
    before_ts=$(date +%s)

    FILEDROP_AGENT="$SENDER" filedrop send "$TARGET" "$subject" "$content" --no-wake 2>/dev/null
    # Wake separately so we get clean output
    FILEDROP_AGENT="$SENDER" filedrop wake "$TARGET" 2>/dev/null || true

    echo "$before_ts"
}

# Poll inbox for a response from Alpha after a given timestamp
# Returns the response content or empty string on timeout
wait_for_response() {
    local after_ts="$1"
    local timeout="$2"
    local deadline=$(($(date +%s) + timeout))

    while [ "$(date +%s)" -lt "$deadline" ]; do
        # Check all JSON files in inbox
        for msg_file in "$INBOX"/*.json; do
            [ -f "$msg_file" ] || continue

            # Parse message: check it's from Alpha and after our send time
            local msg_from msg_ts msg_content
            msg_from=$(jq -r '.from // empty' "$msg_file" 2>/dev/null) || continue
            msg_ts=$(jq -r '.timestamp // 0' "$msg_file" 2>/dev/null) || continue

            if [ "$msg_from" = "$TARGET" ] && [ "$msg_ts" -ge "$after_ts" ]; then
                msg_content=$(jq -r '.content // empty' "$msg_file" 2>/dev/null)
                # Clean up the message
                rm -f "$msg_file" 2>/dev/null || true
                echo "$msg_content"
                return 0
            fi
        done

        sleep "$POLL_INTERVAL"
    done

    # Timeout
    echo ""
    return 1
}

# Run a single test: send message, wait for response, validate
# Args: test_name subject content pattern [timeout]
#   pattern: grep -iP pattern to match against response
run_test() {
    local test_name="$1"
    local subject="$2"
    local content="$3"
    local pattern="$4"
    local timeout="${5:-$DEFAULT_TIMEOUT}"

    log "${BOLD}$test_name${NC}"
    log "  Sending: $content"

    local start_ts
    start_ts=$(date +%s)

    # Clear inbox before each test
    clear_inbox

    # Send and wait
    local send_ts
    send_ts=$(send_message "$subject" "$content")

    local response=""
    local status="pass"
    if response=$(wait_for_response "$send_ts" "$timeout"); then
        if [ -z "$response" ]; then
            status="timeout"
        elif echo "$response" | grep -qiP "$pattern"; then
            status="pass"
        else
            status="fail"
        fi
    else
        status="timeout"
        response=""
    fi

    local end_ts
    end_ts=$(date +%s)
    local duration=$((end_ts - start_ts))

    # Record result
    TEST_NAMES+=("$test_name")
    TEST_DURATIONS+=("${duration}s")

    case "$status" in
        pass)
            log_ok "$test_name (${duration}s)"
            TEST_RESULTS+=("pass")
            TEST_DETAILS+=("Response: ${response:0:200}")
            TESTS_PASSED=$((TESTS_PASSED + 1))
            ;;
        fail)
            log_fail "$test_name (${duration}s) — pattern '$pattern' not found"
            log "  Response: ${response:0:200}"
            TEST_RESULTS+=("fail")
            TEST_DETAILS+=("Expected pattern: $pattern | Got: ${response:0:200}")
            TESTS_FAILED=$((TESTS_FAILED + 1))
            ;;
        timeout)
            log_fail "$test_name (timeout after ${timeout}s)"
            TEST_RESULTS+=("timeout")
            TEST_DETAILS+=("No response within ${timeout}s")
            TESTS_TIMEOUT=$((TESTS_TIMEOUT + 1))
            ;;
    esac
}

# Run a test with filesystem validation instead of response pattern
# Args: test_name subject content file_path file_pattern [timeout]
run_test_file() {
    local test_name="$1"
    local subject="$2"
    local content="$3"
    local file_path="$4"
    local file_pattern="$5"
    local timeout="${6:-$DEFAULT_TIMEOUT}"

    log "${BOLD}$test_name${NC}"
    log "  Sending: $content"

    local start_ts
    start_ts=$(date +%s)

    clear_inbox

    local send_ts
    send_ts=$(send_message "$subject" "$content")

    # Wait for Alpha to process (need response OR file to appear)
    local response=""
    wait_for_response "$send_ts" "$timeout" >/dev/null 2>&1 || true

    local end_ts
    end_ts=$(date +%s)
    local duration=$((end_ts - start_ts))

    TEST_NAMES+=("$test_name")
    TEST_DURATIONS+=("${duration}s")

    # Check filesystem
    if [ -f "$file_path" ] && grep -q "$file_pattern" "$file_path" 2>/dev/null; then
        log_ok "$test_name (${duration}s)"
        TEST_RESULTS+=("pass")
        TEST_DETAILS+=("File $file_path contains '$file_pattern'")
        TESTS_PASSED=$((TESTS_PASSED + 1))
    else
        log_fail "$test_name (${duration}s) — file check failed"
        if [ ! -f "$file_path" ]; then
            log "  File not found: $file_path"
            TEST_DETAILS+=("File not found: $file_path")
        else
            log "  Pattern '$file_pattern' not in $file_path"
            TEST_DETAILS+=("Pattern '$file_pattern' not in $file_path")
        fi
        TEST_RESULTS+=("fail")
        TESTS_FAILED=$((TESTS_FAILED + 1))
    fi
}

# ===========================================================================
# Test cases
# ===========================================================================

test_ping() {
    run_test "ping" "test:ping" \
        "Reply with exactly: PONG" \
        "PONG"
}

test_echo() {
    run_test "echo" "test:echo" \
        "Repeat this word back to me exactly: BUTTERFLY" \
        "BUTTERFLY"
}

test_identity() {
    run_test "identity" "test:identity" \
        "What is your name? Reply with just your name." \
        "Alpha"
}

test_exec() {
    run_test "exec" "test:exec" \
        "Run this shell command and tell me the output: echo hello_from_alpha" \
        "hello_from_alpha"
}

test_file_read() {
    # Pre-create a file for Alpha to read
    local test_content="INTEGRATION_TEST_$(date +%s)"
    echo "$test_content" > /tmp/test_alpha_read.txt

    run_test "file_read" "test:file_read" \
        "Read the file /tmp/test_alpha_read.txt and tell me its exact contents." \
        "$test_content"

    rm -f /tmp/test_alpha_read.txt
}

test_file_write() {
    # Clean up any previous test file
    rm -f /tmp/test_alpha_write.txt

    run_test_file "file_write" "test:file_write" \
        "Write the text ALPHA_WAS_HERE to the file /tmp/test_alpha_write.txt" \
        "/tmp/test_alpha_write.txt" \
        "ALPHA_WAS_HERE"

    rm -f /tmp/test_alpha_write.txt
}

test_filedrop_reply() {
    run_test "filedrop_reply" "test:filedrop_reply" \
        "Send a filedrop message to TestRunner with the subject 'test:reply_ok' and content 'REPLY_CONFIRMED'. Use the filedrop send command." \
        "REPLY_CONFIRMED"
}

# ===========================================================================
# Report generation
# ===========================================================================

generate_report() {
    local total=${#TEST_NAMES[@]}
    local commit_sha
    commit_sha=$(git -C /home/alpha/workspace/cobot rev-parse --short HEAD 2>/dev/null || echo "unknown")

    cat << EOF
# Alpha Integration Test Report

**Date:** $(date -u +"%Y-%m-%d %H:%M:%S UTC")
**Commit:** $commit_sha
**Target:** $TARGET
**Timeout:** ${DEFAULT_TIMEOUT}s

## Summary

| Total | Passed | Failed | Timeout |
|-------|--------|--------|---------|
| $total | $TESTS_PASSED | $TESTS_FAILED | $TESTS_TIMEOUT |

## Results

EOF

    for i in "${!TEST_NAMES[@]}"; do
        local name="${TEST_NAMES[$i]}"
        local result="${TEST_RESULTS[$i]}"
        local duration="${TEST_DURATIONS[$i]}"
        local detail="${TEST_DETAILS[$i]}"

        case "$result" in
            pass)    echo "### ✅ $name ($duration)" ;;
            fail)    echo "### ❌ $name ($duration)" ;;
            timeout) echo "### ⏱️ $name (timeout)" ;;
        esac
        echo "$detail"
        echo ""
    done
}

# ===========================================================================
# Main
# ===========================================================================

main() {
    local tests_to_run=()
    local timeout="$DEFAULT_TIMEOUT"

    # Parse arguments
    while [ $# -gt 0 ]; do
        case "$1" in
            --list)
                echo "Available tests:"
                for t in "${ALL_TESTS[@]}"; do
                    echo "  $t"
                done
                exit 0
                ;;
            --timeout)
                shift
                timeout="$1"
                DEFAULT_TIMEOUT="$timeout"
                ;;
            --report)
                shift
                REPORT_FILE="$1"
                ;;
            --help|-h)
                echo "Usage: $0 [--list] [--timeout N] [--report PATH] [test1 test2 ...]"
                echo ""
                echo "Options:"
                echo "  --list        List available tests"
                echo "  --timeout N   Set response timeout in seconds (default: 120)"
                echo "  --report PATH Save markdown report to file"
                echo "  --help        Show this help"
                echo ""
                echo "Available tests: ${ALL_TESTS[*]}"
                exit 0
                ;;
            -*)
                echo "Unknown option: $1" >&2
                exit 2
                ;;
            *)
                tests_to_run+=("$1")
                ;;
        esac
        shift
    done

    # Default: run all tests
    if [ ${#tests_to_run[@]} -eq 0 ]; then
        tests_to_run=("${ALL_TESTS[@]}")
    fi

    # Validate requested tests exist
    for t in "${tests_to_run[@]}"; do
        if ! declare -f "test_$t" &>/dev/null; then
            echo "ERROR: Unknown test '$t'" >&2
            echo "Available: ${ALL_TESTS[*]}" >&2
            exit 2
        fi
    done

    # Pre-flight
    check_prereqs

    echo ""
    echo -e "${BOLD}Alpha Integration Test Suite${NC}"
    echo -e "Target: $TARGET | Sender: $SENDER | Timeout: ${DEFAULT_TIMEOUT}s"
    echo -e "Tests: ${tests_to_run[*]}"
    echo "==========================================="
    echo ""

    # Run tests
    for t in "${tests_to_run[@]}"; do
        "test_$t"
        # Pause between tests to avoid overwhelming Alpha
        if [ "$t" != "${tests_to_run[-1]}" ]; then
            sleep "$PAUSE_BETWEEN"
        fi
    done

    # Summary
    local total=${#TEST_NAMES[@]}
    echo ""
    echo "==========================================="
    echo -e "${BOLD}Results: ${TESTS_PASSED}/${total} passed${NC}"
    if [ "$TESTS_FAILED" -gt 0 ]; then
        echo -e "${RED}  $TESTS_FAILED failed${NC}"
    fi
    if [ "$TESTS_TIMEOUT" -gt 0 ]; then
        echo -e "${YELLOW}  $TESTS_TIMEOUT timed out${NC}"
    fi

    # Generate report
    if [ -n "$REPORT_FILE" ]; then
        generate_report > "$REPORT_FILE"
        log "Report saved to $REPORT_FILE"
    fi

    # Exit code
    if [ "$TESTS_FAILED" -gt 0 ] || [ "$TESTS_TIMEOUT" -gt 0 ]; then
        exit 1
    fi
    exit 0
}

main "$@"
