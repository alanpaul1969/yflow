"""
Tests for yflow.agents.minimax — M3 step type.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from yflow.agents import minimax
from yflow.agents.minimax import (
    EFFORT_PRESETS,
    _resolve_api_key,
    call_minimax,
    run,
)


class TestEffortPresets(unittest.TestCase):
    def test_all_presets_present(self):
        for effort in ("low", "medium", "high", "max"):
            self.assertIn(effort, EFFORT_PRESETS)
            self.assertIn("max_tokens", EFFORT_PRESETS[effort])
            self.assertIn("temperature", EFFORT_PRESETS[effort])

    def test_max_tokens_increases_with_effort(self):
        prev = 0
        for effort in ("low", "medium", "high", "max"):
            cur = EFFORT_PRESETS[effort]["max_tokens"]
            self.assertGreater(cur, prev)
            prev = cur


class TestApiKeyResolution(unittest.TestCase):
    def setUp(self):
        # Clear all env vars we check
        for k in ("YFLOW_MINIMAX_API_KEY",):
            if k in os.environ:
                del os.environ[k]

    def test_step_override_wins(self):
        self.assertEqual(_resolve_api_key({"api_key": "step-key"}), "step-key")

    def test_env_var_fallback(self):
        os.environ["YFLOW_MINIMAX_API_KEY"] = "env-key"
        self.assertEqual(_resolve_api_key({}), "env-key")

    @unittest.skipIf(os.geteuid() == 0, "running as root, home is /root")
    def test_auth_json_fallback(self):
        # Set up a fake auth.json
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"minimax_api_key": "auth-key"}, f)
            tmp = f.name
        # Patch the home path
        with patch("os.path.expanduser", return_value=tmp):
            with patch("os.path.exists", return_value=True):
                # Patch open to return our tmp
                with patch("builtins.open", create=True, new=unittest.mock.mock_open(read_data='{"minimax_api_key": "auth-key"}')):
                    result = _resolve_api_key({})
                    self.assertEqual(result, "auth-key")
        os.unlink(tmp)


class TestCallMinimax(unittest.TestCase):
    def test_no_api_key_raises(self):
        with self.assertRaises(ValueError) as ctx:
            call_minimax("test", api_key=None)
        self.assertIn("API key", str(ctx.exception))

    @patch("yflow.agents.minimax.urllib.request.urlopen")
    def test_successful_call(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "choices": [{"message": {"content": "Hello back!"}}]
        }).encode("utf-8")
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = lambda s, *a: False
        mock_urlopen.return_value = mock_resp

        result = call_minimax("test prompt", api_key="test-key")
        self.assertEqual(result, "Hello back!")

    @patch("yflow.agents.minimax.urllib.request.urlopen")
    def test_empty_choices_raises(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"choices": []}).encode("utf-8")
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = lambda s, *a: False
        mock_urlopen.return_value = mock_resp

        with self.assertRaises(RuntimeError) as ctx:
            call_minimax("test", api_key="test-key")
        self.assertIn("no choices", str(ctx.exception))


class TestRunStep(unittest.TestCase):
    def setUp(self):
        # Clear env
        for k in ("YFLOW_MINIMAX_API_KEY",):
            if k in os.environ:
                del os.environ[k]

    def test_missing_prompt_raises(self):
        with self.assertRaises(ValueError) as ctx:
            run({"type": "minimax"}, session=None)
        self.assertIn("prompt", str(ctx.exception))

    def test_uses_context_fallback(self):
        with patch("yflow.agents.minimax.call_minimax", return_value="out") as mock_call:
            run({"type": "minimax", "context": "from context", "api_key": "k"}, session=None)
            mock_call.assert_called_once()
            # The prompt passed should be "from context"
            args, kwargs = mock_call.call_args
            self.assertEqual(args[0], "from context")

    def test_effort_preset_applied(self):
        with patch("yflow.agents.minimax.call_minimax", return_value="ok") as mock_call:
            run({"type": "minimax", "prompt": "x", "effort": "low", "api_key": "k"}, session=None)
            args, kwargs = mock_call.call_args
            self.assertEqual(kwargs["max_tokens"], EFFORT_PRESETS["low"]["max_tokens"])
            self.assertEqual(kwargs["temperature"], EFFORT_PRESETS["low"]["temperature"])

    def test_explicit_overrides_effort(self):
        with patch("yflow.agents.minimax.call_minimax", return_value="ok") as mock_call:
            run({
                "type": "minimax", "prompt": "x", "effort": "low",
                "max_tokens": 9999, "temperature": 0.7, "api_key": "k",
            }, session=None)
            args, kwargs = mock_call.call_args
            self.assertEqual(kwargs["max_tokens"], 9999)
            self.assertEqual(kwargs["temperature"], 0.7)

    def test_model_override(self):
        with patch("yflow.agents.minimax.call_minimax", return_value="ok") as mock_call:
            run({"type": "minimax", "prompt": "x", "model": "MiniMax-M2.5", "api_key": "k"}, session=None)
            args, kwargs = mock_call.call_args
            self.assertEqual(kwargs["model"], "MiniMax-M2.5")

    def test_cold_memory_injection(self):
        with patch("yflow.agents.minimax.call_minimax", return_value="ok") as mock_call:
            run({
                "type": "minimax", "prompt": "real task",
                "api_key": "k",
                "_cold_load": ["nonexistent-slug"],  # missing → marker
            }, session=None)
            args, kwargs = mock_call.call_args
            prompt = args[0]
            self.assertIn("Cold memory (auto-injected from yflow memory)", prompt)
            self.assertIn("[missing: nonexistent-slug not found in memory]", prompt)
            self.assertIn("real task", prompt)


if __name__ == "__main__":
    unittest.main()
