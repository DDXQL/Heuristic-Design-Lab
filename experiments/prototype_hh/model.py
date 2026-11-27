"""Scheme-A-only encoding and immutable nearest-prototype selector."""
import math

import numpy as np

from heuristic_design.core import state_a_v3 as state
from heuristic_design.core.storage import digest

KIND = "evolutionary-prototype-router-v1"
ENCODING = "scheme-a-v3-equal-groups-v1"
MAX_BLOCKS = 32


def layout(members):
    if type(members) is not int or members < 1:
        raise ValueError("positive H count required")
    widths = [2] * 10 + [2 * members] * 4 + [members + 4]
    weights = [1 / (len(widths) * width) for width in widths for _ in range(width)]
    return sum(widths), weights


def _number(value, field):
    if value is None:
        return 0.0
    if field.endswith("count"):
        return value / (1 + value)
    return 2 * value if field.endswith("_std") else value


def encode(packet, members):
    # Validation uses host metadata only to reject a wrong contract. Metadata
    # never enters the feature vector, distance, or selected H.
    state.validate_packet(packet, members)
    z = []
    masks = packet["availability"]
    for field in state.NUMERIC_FIELDS:
        z.extend((_number(packet[field], field), float(masks[field])))
    for field in state.H_FIELDS:
        z.extend(_number(value, field) for value in packet[field])
        z.extend(float(flag) for flag in masks[field])
    previous = packet["previous_h_token"]
    z.extend(float(previous == h) for h in range(members))
    z.append(float(previous is None))
    z.extend((float(packet["has_history"]),
              _number(packet["history_count"], "history_count"),
              _number(packet["recent_history_count"], "recent_history_count")))
    return z


def candidate(blocks, members):
    row = {"kind": KIND, "encoding": ENCODING, "state_spec_sha256": state.SPEC_SHA256,
           "member_count": members, "prototypes": blocks}
    validate(row, members)
    return row


def validate(row, members):
    if (not isinstance(row, dict) or set(row) != {
            "kind", "encoding", "state_spec_sha256", "member_count", "prototypes"}
            or row["kind"] != KIND or row["encoding"] != ENCODING
            or row["state_spec_sha256"] != state.SPEC_SHA256
            or type(row["member_count"]) is not int or row["member_count"] != members):
        raise ValueError("prototype model/state/H identity mismatch")
    dimension, _ = layout(members)
    blocks = row["prototypes"]
    if not isinstance(blocks, list) or not 1 <= len(blocks) <= MAX_BLOCKS:
        raise ValueError("prototype count must be in 1..32")
    for block in blocks:
        if not isinstance(block, dict) or set(block) != {"center", "h"}:
            raise ValueError("prototype requires center and H label")
        if type(block["h"]) is not int or not 0 <= block["h"] < members:
            raise ValueError("prototype H label outside frozen set")
        center = block["center"]
        if (not isinstance(center, list) or len(center) != dimension
                or any(type(x) not in (int, float) or not math.isfinite(x)
                       or not -3 <= x <= 3 for x in center)):
            raise ValueError("invalid prototype coordinates")
    return digest(row)


def compile_selector(row, members):
    validate(row, members)
    # Copies prevent later candidate mutation from changing a frozen selector.
    centers = np.array([b["center"] for b in row["prototypes"]], dtype=np.float64)
    labels = tuple(b["h"] for b in row["prototypes"])
    weights = np.array(layout(members)[1], dtype=np.float64)

    def route(packet):
        delta = centers - np.asarray(encode(packet, members), dtype=np.float64)
        distance = np.sum(delta * delta * weights, axis=1)
        return labels[int(np.argmin(distance))]  # first prototype wins exact ties

    return route
