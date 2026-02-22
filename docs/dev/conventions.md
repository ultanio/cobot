# Development Conventions

Guidelines for contributing to Cobot.

## Naming Conventions

### Python Code
- **Variables, functions, methods:** `snake_case`
- **Classes:** `PascalCase`
- **Constants:** `UPPER_SNAKE_CASE`
- **Private members:** `_leading_underscore`

### Configuration Keys (YAML)
- **Always use `snake_case`** for config keys
- Config keys should match their corresponding Python variable names
- Example:
  ```yaml
  heartbeat:
    interval_minutes: 15
    prompt_file: HEARTBEAT.md
    quiet_hours: "23:00-07:00"
  ```

### Plugin IDs
- **lowercase with hyphens:** `my-plugin`
- Keep short and descriptive

### File Names
- **Python files:** `snake_case.py`
- **Markdown:** `UPPER_CASE.md` for root docs, `lower-case.md` for nested docs

## Logging

Use centralized logging via base Plugin class:
```python
self.log_debug("Detailed info for debugging")
self.log_info("Normal operational messages")
self.log_warn("Warning conditions")
self.log_error("Error conditions")
```

Do NOT use `print()` directly in plugins.

## Plugin Structure

Every plugin must have:
- `__init__.py` (can be empty)
- `plugin.py` with:
  - Class inheriting from `Plugin`
  - `meta = PluginMeta(...)` class attribute
  - `create_plugin()` factory function
- `README.md` documenting the plugin

## Git Commits

Follow conventional commits:
- `feat:` new feature
- `fix:` bug fix
- `refactor:` code change that neither fixes nor adds
- `docs:` documentation only
- `test:` adding or updating tests
- `chore:` maintenance tasks

Reference issues: `[#123]` or `Closes #123`

## Pull Requests

- Max 300 lines changed per PR (split larger changes)
- Must include tests for new functionality
- Must pass CI (lint + tests)
- Reference the issue/story being addressed
