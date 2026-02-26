"""Tests for OllamaPlugin."""

from unittest.mock import patch, MagicMock

import pytest

from ..plugin import OllamaPlugin, create_plugin
from ...interfaces import LLMError


class TestCreatePlugin:
    def test_returns_ollama_plugin(self):
        assert isinstance(create_plugin(), OllamaPlugin)

    def test_new_instance(self):
        assert create_plugin() is not create_plugin()


class TestMeta:
    def test_id(self):
        assert create_plugin().meta.id == "ollama"

    def test_capabilities(self):
        assert "llm" in create_plugin().meta.capabilities

    def test_priority(self):
        assert create_plugin().meta.priority == 20


class TestConfigure:
    def test_defaults(self):
        plugin = create_plugin()
        plugin.configure({})
        assert plugin._host == "http://localhost:11434"
        assert plugin._model == "llama3.2:latest"

    def test_custom_host(self):
        plugin = create_plugin()
        plugin.configure({"ollama": {"host": "http://gpu-server:11434"}})
        assert plugin._host == "http://gpu-server:11434"

    def test_strips_trailing_slash(self):
        plugin = create_plugin()
        plugin.configure({"ollama": {"host": "http://localhost:11434/"}})
        assert plugin._host == "http://localhost:11434"

    def test_custom_model(self):
        plugin = create_plugin()
        plugin.configure({"ollama": {"model": "mistral:7b"}})
        assert plugin._model == "mistral:7b"

    @patch.dict("os.environ", {"OLLAMA_HOST": "http://env-host:11434"})
    def test_env_var_fallback(self):
        plugin = create_plugin()
        plugin.configure({})
        assert plugin._host == "http://env-host:11434"

    def test_config_overrides_env(self):
        plugin = create_plugin()
        plugin.configure({"ollama": {"host": "http://config-host:11434"}})
        assert "config-host" in plugin._host


class TestChat:
    @patch("cobot.plugins.ollama.plugin.httpx.post")
    def test_successful_chat(self, mock_post):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "message": {"content": "Hello there!"},
            "model": "llama3.2:latest",
            "prompt_eval_count": 10,
            "eval_count": 5,
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        plugin = create_plugin()
        plugin.configure({})
        result = plugin.chat([{"role": "user", "content": "hi"}])

        assert result.content == "Hello there!"
        assert result.model == "llama3.2:latest"
        assert result.usage["prompt_tokens"] == 10
        assert result.usage["completion_tokens"] == 5

    @patch("cobot.plugins.ollama.plugin.httpx.post")
    def test_chat_with_tool_calls(self, mock_post):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "message": {
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "get_weather",
                            "arguments": '{"city": "Berlin"}',
                        }
                    }
                ],
            },
            "model": "llama3.2:latest",
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        plugin = create_plugin()
        plugin.configure({})
        result = plugin.chat(
            [{"role": "user", "content": "weather?"}],
            tools=[{"type": "function", "function": {"name": "get_weather"}}],
        )

        assert result.tool_calls is not None
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["function"]["name"] == "get_weather"

    @patch("cobot.plugins.ollama.plugin.httpx.post")
    def test_chat_connect_error(self, mock_post):
        import httpx

        mock_post.side_effect = httpx.ConnectError("refused")

        plugin = create_plugin()
        plugin.configure({})
        with pytest.raises(LLMError, match="Cannot connect"):
            plugin.chat([{"role": "user", "content": "hi"}])

    @patch("cobot.plugins.ollama.plugin.httpx.post")
    def test_chat_custom_model(self, mock_post):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "message": {"content": "ok"},
            "model": "mistral:7b",
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        plugin = create_plugin()
        plugin.configure({})
        plugin.chat([{"role": "user", "content": "hi"}], model="mistral:7b")

        payload = mock_post.call_args[1]["json"]
        assert payload["model"] == "mistral:7b"


class TestListModels:
    @patch("cobot.plugins.ollama.plugin.httpx.get")
    def test_list_models(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "models": [{"name": "llama3.2:latest"}, {"name": "mistral:7b"}]
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        plugin = create_plugin()
        plugin.configure({})
        models = plugin.list_models()
        assert "llama3.2:latest" in models
        assert "mistral:7b" in models

    @patch("cobot.plugins.ollama.plugin.httpx.get")
    def test_list_models_error(self, mock_get):
        mock_get.side_effect = Exception("connection refused")

        plugin = create_plugin()
        plugin.configure({})
        with pytest.raises(LLMError):
            plugin.list_models()


class TestGenerate:
    @patch("cobot.plugins.ollama.plugin.httpx.post")
    def test_generate(self, mock_post):
        mock_response = MagicMock()
        mock_response.json.return_value = {"response": "Generated text"}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        plugin = create_plugin()
        plugin.configure({})
        result = plugin.generate("Tell me a joke")
        assert result == "Generated text"


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_offline(self):
        """Start when Ollama is not running."""
        plugin = create_plugin()
        plugin.configure({"ollama": {"host": "http://localhost:99999"}})
        await plugin.start()  # Should warn but not crash

    @pytest.mark.asyncio
    async def test_stop(self):
        plugin = create_plugin()
        await plugin.stop()
