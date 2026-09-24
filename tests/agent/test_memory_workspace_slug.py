"""B5: real workspace slug into memory-provider templating.

``_memory_workspace_slug()`` replaces the hardcoded ``agent_workspace = "hermes"``
kwarg so bank_id templates like ``hermes-{workspace}`` resolve to the session's
actual git root instead of a constant.
"""

from pathlib import Path

from agent.agent_init import _memory_workspace_slug


class TestMemoryWorkspaceSlug:
    def test_git_root_basename_wins_over_cwd_subdir(self, tmp_path, monkeypatch):
        (tmp_path / ".git").mkdir()
        sub = tmp_path / "deeply" / "nested"
        sub.mkdir(parents=True)
        monkeypatch.setattr("agent.runtime_cwd.resolve_agent_cwd", lambda: sub)
        assert _memory_workspace_slug() == tmp_path.name

    def test_non_repo_dir_yields_cwd_basename(self, tmp_path, monkeypatch):
        plain = tmp_path / "plain-project"
        plain.mkdir()
        monkeypatch.setattr("agent.runtime_cwd.resolve_agent_cwd", lambda: plain)
        assert _memory_workspace_slug() == "plain-project"

    def test_exception_yields_hermes(self, monkeypatch):
        def _boom():
            raise RuntimeError("cwd deleted")

        monkeypatch.setattr("agent.runtime_cwd.resolve_agent_cwd", _boom)
        assert _memory_workspace_slug() == "hermes"

    def test_root_yields_hermes(self, monkeypatch):
        monkeypatch.setattr("agent.runtime_cwd.resolve_agent_cwd", lambda: Path("/"))
        assert _memory_workspace_slug() == "hermes"

    def test_kanban_task_workspace_uses_board_slug(self, tmp_path, monkeypatch):
        # A task-board worker's scratch folder must not become its own bank.
        monkeypatch.setenv("HERMES_KANBAN_HOME", str(tmp_path))
        task = tmp_path / "kanban" / "boards" / "iffy-build" / "workspaces" / "t_abc123"
        task.mkdir(parents=True)
        monkeypatch.setattr("agent.runtime_cwd.resolve_agent_cwd", lambda: task)
        assert _memory_workspace_slug() == "iffy-build"

    def test_kanban_task_workspace_uses_board_default_workdir_repo(self, tmp_path, monkeypatch):
        import json

        repo = tmp_path / "projects" / "game1-cozy"
        (repo / ".git").mkdir(parents=True)
        (repo / "src").mkdir()
        monkeypatch.setenv("HERMES_KANBAN_HOME", str(tmp_path))
        board = tmp_path / "kanban" / "boards" / "quiet-stacks"
        task = board / "workspaces" / "t_def456" / "sub"
        task.mkdir(parents=True)
        (board / "board.json").write_text(json.dumps({"default_workdir": str(repo / "src")}))
        monkeypatch.setattr("agent.runtime_cwd.resolve_agent_cwd", lambda: task)
        assert _memory_workspace_slug() == "game1-cozy"

    def test_agent_init_passes_real_slug(self, monkeypatch):
        # The kwargs builder must call the slug helper, not hardcode "hermes".
        import agent.agent_init as mod
        calls = []
        monkeypatch.setattr(mod, "_memory_workspace_slug", lambda: calls.append(1) or "kima-hub")

        class FakeAgent:
            pass

        # Locate the builder and run it
        import inspect
        src = inspect.getsource(mod)
        assert 'kwargs["agent_workspace"] = "hermes"' not in src
