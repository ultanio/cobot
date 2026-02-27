# HEARTBEAT.md - Alpha

## On Each Heartbeat

1. **Check filedrop inbox** — read and respond to any messages
2. **Report status** — log any errors or issues noticed

## FileDrop

Use the `filedrop` CLI or the built-in filedrop plugin to communicate:

```bash
filedrop list                    # Check inbox
filedrop read <file>             # Read a message
filedrop send <agent> <subject> <content>  # Send a reply
filedrop done <file>             # Mark as processed
```

If you receive a message via filedrop, always reply to the sender.
