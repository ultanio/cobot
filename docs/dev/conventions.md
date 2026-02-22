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

## Plugin Metadata

PluginMeta defines a plugin's identity, capabilities, and relationships with other plugins.

### Vocabulary

| Field | Meaning | Graph representation |
|-------|---------|---------------------|
| `capabilities` | I provide this | Node attribute + edge to capability hub |
| `dependencies` | I require this plugin (hard) | Solid edge |
| `optional_dependencies` | I can use this if loaded | Dashed edge |
| `consumes` | I aggregate from this capability group | Edge from capability hub |
| `implements` | I fulfill this extension point | Green edge |
| `extension_points` | I define this contract | Node attribute |

### When to Use Each Field

- **`capabilities`**: Declare what your plugin provides (e.g., `["llm"]`, `["storage"]`). Other plugins find you via `registry.get_by_capability()`.

- **`dependencies`**: Hard requirements. The registry will fail to load your plugin if these aren't present. Use for plugins you directly call.

- **`optional_dependencies`**: Soft dependencies. Your plugin loads even if these are missing. Check at runtime with `registry.get()` and handle `None`.

- **`consumes`**: Capability-based aggregation. Your plugin collects from all plugins with this capability (e.g., consume `"storage"` to aggregate all storage backends).

- **`implements`**: Map extension points to your handler methods. The plugin defining the extension point calls you.

- **`extension_points`**: Define contracts other plugins can implement. You call them via `call_extension()` or `call_extension_chain()`.

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
