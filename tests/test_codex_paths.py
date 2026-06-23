import importlib
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

codex_usage = importlib.import_module("codex_usage")


class CodexPathTests(unittest.TestCase):
    def reload_codex_usage(
        self, *, codex_home: str | None = None, home: Path | None = None
    ):
        env = {"CODEX_HOME": codex_home} if codex_home is not None else {}

        with patch.dict(os.environ, env, clear=False):
            if codex_home is None:
                os.environ.pop("CODEX_HOME", None)
            if home is None:
                module = importlib.reload(codex_usage)
                return module, module.resolve_codex_home()
            with patch.object(Path, "home", return_value=home):
                module = importlib.reload(codex_usage)
                return module, module.resolve_codex_home()

    def tearDown(self) -> None:
        importlib.reload(codex_usage)

    def test_codex_home_uses_codex_home_environment_variable(self) -> None:
        override = Path("C:/Users/Mike/AppData/Roaming/Codex")

        module, resolved = self.reload_codex_usage(codex_home=str(override))

        self.assertEqual(resolved, override)
        self.assertEqual(module.CODEX_HOME, override)
        self.assertEqual(module.AUTH_PATH, override / "auth.json")

    def test_codex_home_defaults_to_dot_codex_under_home(self) -> None:
        home = Path("C:/Users/Mike")
        expected = home / ".codex"

        module, resolved = self.reload_codex_usage(home=home)

        self.assertEqual(resolved, expected)
        self.assertEqual(module.CODEX_HOME, expected)
        self.assertEqual(module.AUTH_PATH, expected / "auth.json")


if __name__ == "__main__":
    unittest.main()
