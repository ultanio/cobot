"""Tests for WalletPlugin."""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from ..plugin import WalletPlugin, create_plugin
from ...interfaces import WalletError


# === Plugin Creation ===


class TestCreatePlugin:
    def test_returns_wallet_plugin(self):
        assert isinstance(create_plugin(), WalletPlugin)

    def test_new_instance(self):
        assert create_plugin() is not create_plugin()


# === Meta ===


class TestMeta:
    def test_id(self):
        assert create_plugin().meta.id == "wallet"

    def test_capabilities(self):
        meta = create_plugin().meta
        assert "wallet" in meta.capabilities
        assert "tools" in meta.capabilities

    def test_priority(self):
        assert create_plugin().meta.priority == 25


# === Configuration ===


class TestConfigure:
    def test_default_scripts_dir(self):
        plugin = create_plugin()
        plugin.configure({})
        assert plugin._scripts_dir == Path("./skills/npubcash/scripts")

    def test_custom_skills_path(self):
        plugin = create_plugin()
        plugin.configure({"paths": {"skills": "/custom/skills"}})
        assert plugin._scripts_dir == Path("/custom/skills/npubcash/scripts")

    def test_wallet_skills_path_override(self):
        plugin = create_plugin()
        plugin.configure({"wallet": {"skills_path": "/override"}})
        assert plugin._scripts_dir == Path("/override/npubcash/scripts")


# === Lifecycle ===


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_scripts_missing(self):
        plugin = create_plugin()
        plugin.configure({})
        await plugin.start()  # Should warn but not crash

    @pytest.mark.asyncio
    async def test_start_scripts_exist(self, tmp_path):
        scripts = tmp_path / "npubcash" / "scripts"
        scripts.mkdir(parents=True)

        plugin = create_plugin()
        plugin.configure({"paths": {"skills": str(tmp_path)}})
        await plugin.start()

    @pytest.mark.asyncio
    async def test_stop(self):
        plugin = create_plugin()
        await plugin.stop()


# === Run Script ===


class TestRunScript:
    def test_not_configured(self):
        plugin = create_plugin()
        plugin._scripts_dir = None
        with pytest.raises(WalletError, match="not configured"):
            plugin._run_script("balance.js")

    def test_script_not_found(self, tmp_path):
        plugin = create_plugin()
        plugin._scripts_dir = tmp_path
        with pytest.raises(WalletError, match="not found"):
            plugin._run_script("nonexistent.js")

    @patch("cobot.plugins.wallet.plugin.subprocess.run")
    def test_successful_run(self, mock_run, tmp_path):
        script = tmp_path / "test.js"
        script.write_text("// fake")

        mock_run.return_value = MagicMock(returncode=0, stdout="output", stderr="")

        plugin = create_plugin()
        plugin._scripts_dir = tmp_path
        plugin._env = {}
        result = plugin._run_script("test.js")

        assert result == "output"

    @patch("cobot.plugins.wallet.plugin.subprocess.run")
    def test_script_failure(self, mock_run, tmp_path):
        script = tmp_path / "fail.js"
        script.write_text("// fake")

        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error msg")

        plugin = create_plugin()
        plugin._scripts_dir = tmp_path
        plugin._env = {}
        with pytest.raises(WalletError, match="error msg"):
            plugin._run_script("fail.js")

    @patch("cobot.plugins.wallet.plugin.subprocess.run")
    def test_script_timeout(self, mock_run, tmp_path):
        import subprocess

        script = tmp_path / "slow.js"
        script.write_text("// fake")

        mock_run.side_effect = subprocess.TimeoutExpired(cmd="node", timeout=30)

        plugin = create_plugin()
        plugin._scripts_dir = tmp_path
        plugin._env = {}
        with pytest.raises(WalletError, match="timed out"):
            plugin._run_script("slow.js")

    @patch("cobot.plugins.wallet.plugin.subprocess.run")
    def test_passes_args(self, mock_run, tmp_path):
        script = tmp_path / "test.js"
        script.write_text("// fake")

        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")

        plugin = create_plugin()
        plugin._scripts_dir = tmp_path
        plugin._env = {}
        plugin._run_script("test.js", ["arg1", "arg2"])

        cmd = mock_run.call_args[0][0]
        assert "arg1" in cmd
        assert "arg2" in cmd


# === WalletProvider Interface ===


class TestGetBalance:
    @patch.object(WalletPlugin, "_run_script")
    def test_parse_balance(self, mock_script):
        mock_script.return_value = "Token balance: 1500 sats"
        plugin = create_plugin()
        assert plugin.get_balance() == 1500

    @patch.object(WalletPlugin, "_run_script")
    def test_zero_balance(self, mock_script):
        mock_script.return_value = "no balance info"
        plugin = create_plugin()
        assert plugin.get_balance() == 0


class TestPay:
    @patch.object(WalletPlugin, "_run_script")
    def test_successful_pay(self, mock_script):
        mock_script.return_value = "Payment sent!"
        plugin = create_plugin()
        result = plugin.pay("lnbc1...")
        assert result["success"] is True

    @patch.object(WalletPlugin, "_run_script")
    def test_failed_pay(self, mock_script):
        mock_script.side_effect = WalletError("insufficient funds")
        plugin = create_plugin()
        result = plugin.pay("lnbc1...")
        assert result["success"] is False
        assert "insufficient" in result["error"]


class TestGetReceiveAddress:
    @patch.object(WalletPlugin, "_run_script")
    def test_parse_address(self, mock_script):
        mock_script.return_value = "Your address: agent@npub.cash\nDone"
        plugin = create_plugin()
        assert plugin.get_receive_address() == "agent@npub.cash"

    @patch.object(WalletPlugin, "_run_script")
    def test_no_address(self, mock_script):
        mock_script.return_value = "no address found"
        plugin = create_plugin()
        assert plugin.get_receive_address() == ""


# === Tool Provider ===


class TestToolProvider:
    def test_get_definitions(self):
        plugin = create_plugin()
        defs = plugin.get_definitions()
        names = [d["function"]["name"] for d in defs]
        assert "wallet_balance" in names
        assert "wallet_pay" in names
        assert "wallet_receive" in names

    @patch.object(WalletPlugin, "get_balance", return_value=2000)
    def test_tool_balance(self, _mock):
        plugin = create_plugin()
        result = plugin.execute("wallet_balance", {})
        assert "2000" in result

    @patch.object(WalletPlugin, "get_balance", side_effect=WalletError("no wallet"))
    def test_tool_balance_error(self, _mock):
        plugin = create_plugin()
        result = plugin.execute("wallet_balance", {})
        assert "Error" in result

    @patch.object(WalletPlugin, "pay", return_value={"success": True})
    def test_tool_pay(self, _mock):
        plugin = create_plugin()
        result = plugin.execute("wallet_pay", {"invoice": "lnbc1..."})
        assert "successful" in result

    def test_tool_pay_no_invoice(self):
        plugin = create_plugin()
        result = plugin.execute("wallet_pay", {})
        assert "required" in result

    @patch.object(WalletPlugin, "get_receive_address", return_value="me@npub.cash")
    def test_tool_receive(self, _mock):
        plugin = create_plugin()
        result = plugin.execute("wallet_receive", {})
        assert "me@npub.cash" in result

    def test_unknown_tool(self):
        plugin = create_plugin()
        result = plugin.execute("nonexistent", {})
        assert "Unknown" in result
