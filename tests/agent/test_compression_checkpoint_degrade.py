"""Fail-closed compaction degrade behavior (remediation C1).

``compression.checkpoint_required`` refuses to compact without a durable
pre-compress checkpoint. The refusal itself must never kill the turn: a
Hindsight outage costs context-window headroom (compaction skipped, full
transcript handed back), never the transcript and never the session.
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
from unittest.mock import patch

from agent.conversation_compression import compress_context
from agent.memory_manager import MemoryManager
from agent.memory_provider import PRE_COMPRESS_CHECKPOINT_API_VERSION, MemoryProvider
from hermes_state import SessionDB


def _build_agent(tmp_path: Path, session_id: str):
    db = SessionDB(db_path=tmp_path / "state.db")
    db.create_session(session_id, source="cli")
    with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
        from run_agent import AIAgent

        agent = AIAgent(
            api_key="test-key",
            base_url="https://openrouter.ai/api/v1",
            model="test/model",
            quiet_mode=True,
            session_db=db,
            session_id=session_id,
            skip_context_files=True,
            skip_memory=True,
        )
    agent._compression_feasibility_checked = True
    agent.compression_in_place = True
    agent._cached_system_prompt = "sys"
    agent.context_compressor.threshold_tokens = 1_000
    return db, agent


def _messages():
    return [{"role": "user", "content": f"m{i}"} for i in range(20)]


class _CheckpointProvider(MemoryProvider):
    """v2 provider whose checkpoint either succeeds or fails on demand."""

    pre_compress_checkpoint_api_version = PRE_COMPRESS_CHECKPOINT_API_VERSION

    def __init__(self, name="durable", fail=False):
        self._name, self._fail = name, fail
        self.calls = []

    @property
    def name(self):
        return self._name

    def is_available(self):
        return True

    def initialize(self, session_id, **kwargs):
        return None

    def get_tool_schemas(self):
        return []

    def on_pre_compress(self, messages, *, require_checkpoint=False, **kwargs):
        self.calls.append({"require_checkpoint": require_checkpoint, "n": len(messages)})
        if self._fail:
            raise RuntimeError("durable store unreachable")
        return "Hindsight checkpoint: 20 messages retained to bank test-bank (document doc-1)"


def _install_manager(agent, provider):
    manager = MemoryManager()
    manager.add_provider(provider)
    agent._memory_manager = manager
    return manager


class TestCheckpointUnavailableDegrades:

    def test_no_memory_manager_skips_compression_transcript_intact(self, tmp_path: Path):
        db, agent = _build_agent(tmp_path, "CKPT_DEGRADE_NOMANAGER")
        agent.compression_checkpoint_required = True
        assert getattr(agent, "_memory_manager", None) is None or not agent._memory_manager.providers
        live = _messages()
        before = copy.deepcopy(live)
        out, prompt = compress_context(agent, live, "sys", approx_tokens=500_000)
        assert out == before, "refused checkpoint must hand the FULL transcript back uncompressed"
        assert live == before
        assert prompt == "sys"

    def test_failing_v2_provider_skips_compression_transcript_intact(self, tmp_path: Path):
        db, agent = _build_agent(tmp_path, "CKPT_DEGRADE_FAILPROV")
        agent.compression_checkpoint_required = True
        provider = _CheckpointProvider(fail=True)
        _install_manager(agent, provider)
        live = _messages()
        before = copy.deepcopy(live)
        out, prompt = compress_context(agent, live, "sys", approx_tokens=500_000)
        assert out == before and live == before
        assert provider.calls and provider.calls[0]["require_checkpoint"] is True
        # Session stays writable; no lease stranded.
        db.append_message("CKPT_DEGRADE_FAILPROV", "assistant", "still writable")
        assert db.get_compression_lock_holder("CKPT_DEGRADE_FAILPROV") is None

    def test_healthy_v2_provider_compression_proceeds_with_checkpoint_line(self, tmp_path: Path):
        db, agent = _build_agent(tmp_path, "CKPT_DEGRADE_HEALTHY")
        agent.compression_checkpoint_required = True
        provider = _CheckpointProvider()
        _install_manager(agent, provider)
        seen_kwargs = []

        def recorder(messages, **kwargs):
            seen_kwargs.append(kwargs)
            return [{"role": "assistant", "content": "summary"}]

        agent.context_compressor.compress = recorder
        live = _messages()
        out, _prompt = compress_context(agent, live, "sys", approx_tokens=500_000)
        assert provider.calls and provider.calls[0]["require_checkpoint"] is True
        assert seen_kwargs, "compression must proceed when the checkpoint succeeds"
        ctx = seen_kwargs[0].get("memory_context", "")
        assert "Hindsight checkpoint" in ctx, "checkpoint line must reach the summarizer prompt"
        assert any(m.get("content") == "summary" for m in out), "compacted transcript must carry the summary"
        assert len(out) < len(live), "the attempt must actually compact"

    def test_checkpoint_required_false_keeps_best_effort_swallow(self, tmp_path: Path):
        db, agent = _build_agent(tmp_path, "CKPT_DEGRADE_BESTEFFORT")
        agent.compression_checkpoint_required = False
        provider = _CheckpointProvider(fail=True)
        _install_manager(agent, provider)

        def recorder(messages, **kwargs):
            return [{"role": "assistant", "content": "summary"}]

        agent.context_compressor.compress = recorder
        live = _messages()
        out, _prompt = compress_context(agent, live, "sys", approx_tokens=500_000)
        assert provider.calls and provider.calls[0]["require_checkpoint"] is False
        assert any(m.get("content") == "summary" for m in out), "best-effort mode must still compact"
        assert len(out) < len(live)
