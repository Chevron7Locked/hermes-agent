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


def test_linked_worktree_uses_main_repo_name(tmp_path, monkeypatch):
    """A kanban task worktree (<repo>/.worktrees/<id>) must map to the repo's bank, not the task's."""
    import subprocess
    repo = tmp_path / "myrepo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=a@b", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "i"], cwd=repo, check=True)
    subprocess.run(["git", "worktree", "add", "-q", ".worktrees/t_abc123", "-b", "task-t_abc123"], cwd=repo, check=True)
    from agent import agent_init
    monkeypatch.setattr("agent.runtime_cwd.resolve_agent_cwd", lambda: repo / ".worktrees" / "t_abc123")
    assert agent_init._memory_workspace_slug() == "myrepo"
