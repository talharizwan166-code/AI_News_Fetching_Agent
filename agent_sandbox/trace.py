"""Commit reservations before external calls, preserving evidence on timeout."""

from datetime import datetime, timezone

from chatcheck.storage import Storage
from .safety import SandboxLimit


class Trace:
    def __init__(self, db, test_id, *, max_steps=30, max_calls=4, max_tokens=16000):
        self.storage = Storage(db)
        self.test_id = test_id
        self.seq = len(self.storage.agent_events(test_id))
        self.steps = self.calls = self.tokens = 0
        self.max_steps, self.max_calls, self.max_tokens = max_steps, max_calls, max_tokens

    def emit(self, action, arguments, *, status="ok", result=None):
        if status != "blocked" and self.steps >= self.max_steps:
            self.emit("budget_exceeded", {"budget": "steps"}, status="blocked")
            raise SandboxLimit("Sandbox step cap reached")
        self.seq += 1
        self.steps += status != "blocked"
        event = {"seq": self.seq, "timestamp": datetime.now(timezone.utc).isoformat(),
                 "action": action, "arguments": arguments, "status": status, "result": result or {}}
        self.storage.record_event(self.test_id, event)
        return event

    def finish(self, event, result=None, status="ok"):
        import json
        with self.storage.connection:
            self.storage.connection.execute(
                "UPDATE agent_events SET status=?, result_json=? WHERE test_id=? AND seq=?",
                (status, json.dumps(result or {}, ensure_ascii=False), self.test_id, event["seq"]))

    def reserve_llm(self, prompt, output_cap):
        # UTF-8 bytes are a deliberately conservative token upper bound.
        reserve = len(prompt.encode("utf-8")) + output_cap
        if self.calls >= self.max_calls or self.tokens + reserve > self.max_tokens:
            self.emit("budget_exceeded", {"budget": "llm_calls" if self.calls >= self.max_calls else "tokens"}, status="blocked")
            raise SandboxLimit("Sandbox LLM budget reached")
        self.calls += 1
        self.tokens += reserve
        return reserve
