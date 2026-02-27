# TOOLS.md - Alpha

## FileDrop CLI

Use the `filedrop` CLI for inter-agent communication:

```bash
filedrop list                    # Check inbox
filedrop read <file>             # Read a message
filedrop send <agent> <subject> <content>  # Send a message
filedrop done <file>             # Mark as processed
```

Base directory: `/olymp/filedrop/`

## Environment

- **Workspace:** `~/.cobot/workspace/`
- **Config:** `~/.cobot/cobot.yml`
- **Secrets:** `~/secrets/cobot.env`
