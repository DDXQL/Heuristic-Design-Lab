"""Opt-in response counting and retries above the frozen V5 wire."""

from collections import Counter
from dataclasses import replace

from fjsp_usage.research_real.attempt_budget import AttemptJournal, failure_policy
from fjsp_usage.research_real.real_transport import JsonCandidateTransport, TransportError
from heuristic_design.core.storage import digest
from heuristic_design.llm.legacy import ClientConfig, DeadlineTransport, WireRecorder
from .configuration import request_timeout

VERSION = "successful-evolution-responses-v1"
TIME_PAUSE = "slurm_walltime_drain"
BUDGET_PAUSE = "evolution_attempt_budget_exhausted"
STREAK_PAUSE = "member_transport_failure_limit"


def validate(policy, target, *, real=False):
    fields = {
        "version", "adoption", "research_record", "empty", "truncated",
        "evolution_attempt_cap", "per_slot_attempt_cap", "backoff_seconds",
        "failure_streak_limit", "retry_explicit_429", "rate_limit_backoff_seconds",
    }
    if not isinstance(policy, dict) or set(policy) != fields or policy["version"] != VERSION:
        raise ValueError("explicit successful-candidate policy fields required")
    if policy["adoption"] not in ("draft", "adopted"):
        raise ValueError("invalid candidate policy adoption state")
    if real and (policy["adoption"] != "adopted" or not str(policy["research_record"] or "").strip()
                 or not isinstance(policy["research_record"], str)):
        raise PermissionError("candidate policy requires a research adoption record before a real plan")
    cap, per_slot = policy["evolution_attempt_cap"], policy["per_slot_attempt_cap"]
    backoff = policy["backoff_seconds"]
    if (type(cap) is not int or type(per_slot) is not int or not 1 <= per_slot <= 5
            or cap < target
            or not isinstance(backoff, list) or len(backoff) != per_slot - 1
            or any(type(s) is not int or not 1 <= s <= 60 for s in backoff)
            or type(policy["failure_streak_limit"]) is not int or not 0 <= policy["failure_streak_limit"] <= 100
            or type(policy["retry_explicit_429"]) is not bool
            or type(policy["rate_limit_backoff_seconds"]) is not int
            or not 1 <= policy["rate_limit_backoff_seconds"] <= 300
            or policy["empty"] not in ("exclude", "count_invalid")
            or policy["truncated"] not in ("exclude", "count_invalid")):
        raise ValueError("invalid candidate response or bounded transport policy")


def failure(policy, message, meta, error_type):
    temporary, category, permanent = failure_policy(message, meta, error_type)
    status = meta.get("http_status")
    sent = meta.get("send_status")
    terminal_http = (sent == "confirmed" and meta.get("failure_stage") == "http_receive"
                     and type(status) is int and 400 <= status <= 599)
    not_sent = sent in ("not_sent", "not_started")
    if permanent or meta.get("caller_hard_stop"):
        return False, category, True
    if (meta.get("independent_batch") and meta.get("dispatch_children_settled") is True
            and not (not_sent or terminal_http)):
        return False, "wire_outcome_unknown_charged", False
    if meta.get("dispatch_children_settled") is not True or not (not_sent or terminal_http):
        return False, "unresolved_send_or_worker", True
    explicit_429 = (terminal_http and status == 429
                    and meta.get("error_code") == "rate_limit_exceeded")
    retry = (not_sent and temporary and not meta.get("shared_stop")
             or explicit_429 and not meta.get("independent_batch") and policy["retry_explicit_429"])
    return retry, "terminal_http_" + str(status) if terminal_http else category, False


class CandidateTransport(JsonCandidateTransport):
    """Accept optional usage and classify identifiable empty/truncated replies."""

    def __init__(self, config, policy):
        if config.provider.stream_response is not False:
            raise ValueError("candidate policy requires frozen V5 nonstream transport")
        super().__init__(config)
        self.policy = policy
        self.identity = digest({"wire": self.identity, "candidate_policy": policy})

    def dispatch(self, *args, **kwargs):
        try:
            reply = super().dispatch(*args, **kwargs)
        except TransportError as exc:
            meta = getattr(exc, "metadata", {}) or {}
            if (meta.get("http_status") == 200 and meta.get("model") == self.provider.expected_response_model
                    and meta.get("finish_reason") == "length" and meta.get("content_type") == "str"
                    and not meta.get("refusal_present") and not meta.get("tool_calls_present")):
                return {"text": "", "usage": getattr(exc, "usage", None),
                        "metadata": {**meta, "response_class": "truncated"}}
            if meta.get("http_status") == 200 and meta.get("model") not in (None, self.provider.expected_response_model):
                exc.metadata = {**meta, "caller_hard_stop": True}
            raise
        if not reply["text"].strip():
            reply["metadata"]["response_class"] = "empty"
        return reply


class CandidateJournal(AttemptJournal):
    retain_prompt = False

    def __init__(self, *args, candidate_policy, initialization_cap, **kwargs):
        self.candidate_policy = candidate_policy
        self.phase_caps = {"initialization": initialization_cap,
                           "evolution": candidate_policy["evolution_attempt_cap"]}
        self.current_stage = None
        super().__init__(*args, **kwargs)

    def request_candidate(self, key, prompt, kind, task):
        stage = "initialization" if task["operator"] in ("INIT", "I1") else "evolution"
        previous = self.data["requests"].get(key)
        if previous and previous["stage"] != stage:
            raise ValueError("attempt phase changed on resume")
        self.current_stage = stage
        reply = self.request(key, prompt, kind=kind)
        response_class = reply.get("response_metadata", {}).get("response_class")
        if reply["status"] == "completed" and not reply["text"].strip() and not response_class:
            response_class = "empty"
        task["excluded_response"] = response_class in ("empty", "truncated") and self.candidate_policy[response_class] == "exclude"
        task["response_class"] = response_class
        task["attempt_stage_exhausted"] = self.stage_attempts(stage) >= self.phase_caps[stage]
        return reply

    def request_fields(self):
        return {"stage": self.current_stage}

    def stage_attempts(self, stage):
        return sum(len(r["attempt_ids"]) for r in self.data["requests"].values() if r["stage"] == stage)

    def attempt_allowed(self, record):
        stage = record["stage"]
        return (self.stage_attempts(stage) < self.phase_caps[stage]
                and (stage != "initialization" or not record["attempt_ids"]))

    def classify_failure(self, message, metadata=None, error_type=""):
        return failure(self.candidate_policy, message, metadata or {}, error_type)


def client_config(protocol):
    config = ClientConfig(protocol)
    timeout = request_timeout(protocol['config'])
    provider = config.provider
    if timeout < provider.total_timeout:
        config.provider = replace(provider, total_timeout=timeout, read_timeout=min(timeout, provider.read_timeout))
    return config


def journal(adapter, directory, state, protocol, deadline):
    c = protocol["config"]
    policy = c["candidate_policy"]
    config = client_config(protocol)
    config.request_budget["retry_backoff_seconds"] = policy["backoff_seconds"]
    inner = adapter.transport(protocol)
    wire = WireRecorder(inner, directory / "wire_responses")
    return CandidateJournal(directory / "API_attempts.json", config=config, context=state["identity"],
                            phase="operations/" + state["identity"], transport=DeadlineTransport(wire, deadline),
                            candidate_policy=policy, initialization_cap=c["initialization_request_cap"])


def costs(journal):
    requests = journal.get("requests", {})
    attempts = list(journal.get("api_attempts", {}).values())
    return {
        "reservations_by_stage": dict(Counter(requests[a["logical_id"]]["stage"] for a in attempts)),
        "physical_sends_confirmed": sum(a["send_confirmed"] for a in attempts),
        "physical_sends_unknown": sum(a["status"] in ("pending", "interrupted_unknown")
                                      or (a.get("metadata") or {}).get("send_status") == "unknown" for a in attempts),
        "unresolved_wire_outcomes": sum(a.get("retry_reason") == "wire_outcome_unknown_charged" for a in attempts),
        "retry_reservations": sum(a["number"] > 1 for a in attempts),
        "retry_physical_sends_confirmed": sum(a["number"] > 1 and a["send_confirmed"] for a in attempts),
        "confirmed_sends_usage_unknown": sum(a["send_confirmed"] and a.get("usage") is None for a in attempts),
        "known_tokens": {k: sum(a["usage"][k] for a in attempts if a.get("usage") is not None)
                         for k in ("input_tokens", "output_tokens")},
    }
