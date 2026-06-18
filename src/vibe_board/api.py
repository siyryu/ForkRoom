from abc import ABC, abstractmethod
from typing import Dict, Sequence

from .codex_focus import CodexFocusSummary


class AgentProvider(ABC):
    @abstractmethod
    def get_run_states(self, session_ids: Sequence[str], timeout_seconds: float = 4.0) -> Dict[str, str]:
        """
        Returns a mapping from session_id to its run state.
        States typically include: 'active', 'waiting', 'failed', 'completed', 'idle', 'error', 'unknown'.
        """
        pass

    @abstractmethod
    def get_focus(self, session_id: str, timeout_seconds: float = 4.0) -> CodexFocusSummary:
        """
        Returns the current focus of the given session.
        """
        pass


class CodexProvider(AgentProvider):
    def get_run_states(self, session_ids: Sequence[str], timeout_seconds: float = 4.0) -> Dict[str, str]:
        from .codex_status import load_codex_run_states
        return load_codex_run_states(session_ids, timeout_seconds)

    def get_focus(self, session_id: str, timeout_seconds: float = 4.0) -> CodexFocusSummary:
        from .codex_focus import load_codex_focus
        return load_codex_focus(session_id, timeout_seconds)

