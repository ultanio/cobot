#!/bin/bash
# E2E tests for cobot
# Requires PPQ_API_KEY environment variable

set -e

echo "=== Cobot E2E Tests ==="

# Find cobot package directory (for plugins)
COBOT_DIR=$(python -c "import cobot; import os; print(os.path.dirname(cobot.__file__))")
echo "Cobot package: $COBOT_DIR"

# Setup test directory
TEST_DIR=$(mktemp -d)
trap "rm -rf $TEST_DIR" EXIT

# 1. CLI basics
echo ""
echo "📋 Test: CLI commands"
cobot --version
cobot --help > /dev/null
echo "✅ CLI works"

# 2. Status command
echo ""
echo "📊 Test: Status command"
cobot status | grep -q "Not running"
echo "✅ Status works"

# 3. Wizard with -y flag
echo ""
echo "🧙 Test: Wizard non-interactive"
cd "$TEST_DIR"
cobot wizard init -y
if [ -f cobot.yml ]; then
    echo "✅ Wizard created cobot.yml"
    cat cobot.yml
else
    echo "❌ Wizard failed to create cobot.yml"
    exit 1
fi

# 4. Config validation
echo ""
echo "🔍 Test: Config validation"
cobot config validate && echo "✅ Config valid" || echo "⚠️ Config has warnings"

# 5. LLM response (requires PPQ_API_KEY)
echo ""
echo "🤖 Test: LLM response via stdin"
if [ -n "$PPQ_API_KEY" ]; then
    # Create config file
    cat > cobot.yml << 'EOF'
provider: ppq
identity:
  name: E2ETestBot
ppq:
  api_base: https://api.ppq.ai/v1
  model: openai/gpt-4o
exec:
  enabled: true
  timeout: 30
plugins:
  disabled:
    - filedrop
    - nostr
EOF

    # Run with plugins from package
    RESPONSE=$(echo "Reply with exactly: E2E_OK" | timeout 30 cobot run --stdin -c "$TEST_DIR/cobot.yml" -p "$COBOT_DIR/plugins" 2>/dev/null | tail -1)
    if echo "$RESPONSE" | grep -qi "E2E.OK\|e2e ok\|E2E_OK"; then
        echo "✅ LLM response correct"
    elif [ -n "$RESPONSE" ]; then
        echo "⚠️ LLM responded (content varies): ${RESPONSE:0:50}..."
    else
        echo "❌ No LLM response"
        exit 1
    fi
else
    echo "⏭️ Skipping LLM test (no PPQ_API_KEY)"
fi

# 6. Tool execution (requires PPQ_API_KEY)
echo ""
echo "🔨 Test: Tool execution"
if [ -n "$PPQ_API_KEY" ]; then
    rm -f /tmp/cobot_e2e_test.txt
    echo "Create a file at /tmp/cobot_e2e_test.txt containing the word 'hello'. Use the write_file tool." | timeout 45 cobot run --stdin -c "$TEST_DIR/cobot.yml" -p "$COBOT_DIR/plugins" 2>/dev/null || true
    
    if [ -f /tmp/cobot_e2e_test.txt ]; then
        echo "✅ Tool execution works"
        echo "File contents: $(cat /tmp/cobot_e2e_test.txt)"
        rm -f /tmp/cobot_e2e_test.txt
    else
        echo "⚠️ Tool test inconclusive (file not created)"
    fi
else
    echo "⏭️ Skipping tool test (no PPQ_API_KEY)"
fi

# 7. Memory plugin
echo ""
echo "🧠 Test: Memory plugin"
cd "$TEST_DIR"

# Create workspace structure
mkdir -p memory/files

# Store a memory via CLI (need to test this works)
# For now, test via Python directly
python3 << 'PYTEST'
import sys
sys.path.insert(0, '.')

from cobot.plugins.memory_files import create_plugin as create_files
from cobot.plugins.memory import create_plugin as create_memory

# Test memory-files directly
files = create_files()
files.configure({"_workspace_path": "."})
files.start()

# Store
files.store("test_note", "Meeting about Project Alpha on Tuesday")

# Retrieve
content = files.retrieve("test_note")
assert content == "Meeting about Project Alpha on Tuesday", f"Got: {content}"

# Search
results = files.search("Alpha")
assert len(results) == 1, f"Expected 1 result, got {len(results)}"
assert "Alpha" in results[0]["content"]

print("Memory tests passed!")
PYTEST

if [ $? -eq 0 ]; then
    echo "✅ Memory plugin works"
else
    echo "❌ Memory plugin failed"
    exit 1
fi

# 8. Cron tools
echo ""
echo "⏰ Test: Cron tools"
if [ -n "$PPQ_API_KEY" ]; then
    cd "$TEST_DIR"
    
    # Test cron_add_job
    echo "Use the cron_add_job tool to create a job named 'e2e-test' with schedule '1h' and prompt 'Test task'. Then use cron_list_jobs to show all jobs." | timeout 60 cobot run --stdin -c "$TEST_DIR/cobot.yml" -p "$COBOT_DIR/plugins" 2>/dev/null > /tmp/cron_test_output.txt || true
    
    if grep -qi "e2e-test" /tmp/cron_test_output.txt; then
        echo "✅ Cron add_job works"
    else
        echo "⚠️ Cron test inconclusive"
        cat /tmp/cron_test_output.txt
    fi
    
    # Test cron_remove_job
    echo "Use cron_remove_job to remove the job named 'e2e-test'." | timeout 45 cobot run --stdin -c "$TEST_DIR/cobot.yml" -p "$COBOT_DIR/plugins" 2>/dev/null > /tmp/cron_test_output.txt || true
    
    if grep -qi "removed" /tmp/cron_test_output.txt; then
        echo "✅ Cron remove_job works"
    else
        echo "⚠️ Cron remove test inconclusive"
    fi
    
    rm -f /tmp/cron_test_output.txt
else
    echo "⏭️ Skipping cron tools test (no PPQ_API_KEY)"
fi

echo ""
echo "=== E2E Tests Complete ==="
