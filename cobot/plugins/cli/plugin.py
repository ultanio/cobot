"""CLI plugin - defines the cli.commands extension point.

Other plugins can implement cli.commands to register their CLI commands.
"""

from cobot.plugins.base import Plugin, PluginMeta


class CLIPlugin(Plugin):
    """CLI plugin providing the cli.commands extension point.

    Plugins that want to contribute CLI commands should:
    1. Implement a register_commands(self, cli) method
    2. Declare implements={"cli.commands": "register_commands"} in their PluginMeta
    """

    meta = PluginMeta(
        id="cli",
        version="1.0.0",
        extension_points=["cli.commands"],
        priority=5,  # Foundation layer — load early
    )

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass
