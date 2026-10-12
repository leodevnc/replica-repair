"""Causal multi-value registers with explicit tombstones and bounded inputs."""

from dataclasses import dataclass
import json
import re

MAX_ACTORS = 32
MAX_KEYS = 2048
MAX_SIBLINGS = 64
MAX_COUNTER = 2**63 - 1


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,32}", value):
        raise ValueError("Replica IDs must contain 1-32 ASCII letters, digits, underscores or hyphens")
    return value


def key_name(key):
    if not isinstance(key, str) or not 1 <= len(key) <= 128:
        raise ValueError("Keys must contain 1-128 characters")
    return key


@dataclass(frozen=True)
class Version:
    clock: tuple[tuple[str, int], ...]
    value: str | None  # None is a deletion, never an absent record.

    def __post_init__(self):
        if type(self.clock) is not tuple or not 1 <= len(self.clock) <= MAX_ACTORS:
            raise ValueError("Clock requires 1-32 actors")
        names = []
        for pair in self.clock:
            if type(pair) is not tuple or len(pair) != 2:
                raise ValueError("Invalid clock entry")
            actor, count = pair
            identifier(actor)
            if type(count) is not int or not 1 <= count <= MAX_COUNTER:
                raise ValueError("Clock counters must be positive 63-bit integers")
            names.append(actor)
        if names != sorted(set(names)):
            raise ValueError("Clock actors must be unique and sorted")
        if self.value is not None and (not isinstance(self.value, str) or len(self.value) > 4096):
            raise ValueError("Value must be text of at most 4096 characters or a tombstone")

    def as_dict(self):
        return {"clock": dict(self.clock), "value": self.value}

    @classmethod
    def parse(cls, data):
        if type(data) is not dict or set(data) != {"clock", "value"} or type(data["clock"]) is not dict:
            raise ValueError("Invalid version record")
        # Validate actor types before sorting mixed untrusted input.
        for actor in data["clock"]:
            identifier(actor)
        return cls(tuple(sorted(data["clock"].items())), data["value"])


def dominates(left, right):
    """Strict causal dominance; equal clocks do not dominate one another."""
    a, b = dict(left.clock), dict(right.clock)
    return a != b and all(a.get(actor, 0) >= count for actor, count in b.items())


def merge_versions(*groups):
    by_clock = {}
    for group in groups:
        for version in group:
            if not isinstance(version, Version):
                raise ValueError("Expected a Version")
            previous = by_clock.get(version.clock)
            if previous is not None and previous.value != version.value:
                raise ValueError("Conflicting payloads reuse the same causal clock")
            by_clock[version.clock] = version
    versions = list(by_clock.values())
    maximal = [v for v in versions if not any(dominates(other, v) for other in versions)]
    if len(maximal) > MAX_SIBLINGS:
        raise ValueError("Sibling capacity exceeded; no versions were discarded")
    return tuple(sorted(maximal, key=lambda v: canonical(v.as_dict())))


def parse_records(records):
    if type(records) is not dict or len(records) > MAX_KEYS:
        raise ValueError("Invalid records or key capacity exceeded")
    result = {}
    for key, values in records.items():
        key_name(key)
        if type(values) is not list or not 1 <= len(values) <= MAX_SIBLINGS:
            raise ValueError("Each key requires 1-64 versions")
        result[key] = merge_versions(tuple(Version.parse(item) for item in values))
    return result


class Replica:
    """Single-threaded, in-memory replica. Never run two writers with the same ID."""

    def __init__(self, replica_id):
        self.replica_id = identifier(replica_id)
        self.sequence = 0
        self._data = {}

    def records(self):
        return {key: [v.as_dict() for v in self._data[key]] for key in sorted(self._data)}

    def siblings(self, key):
        return self._data.get(key_name(key), ())

    def read(self, key):
        versions = self.siblings(key)
        if not versions:
            return {"status": "missing", "siblings": []}
        status = "conflict" if len(versions) > 1 else "deleted" if versions[0].value is None else "value"
        return {"status": status, "siblings": [v.as_dict() for v in versions]}

    def put(self, key, value):
        """Explicitly replaces all versions currently observed at this replica for the key."""
        key_name(key)
        if key not in self._data and len(self._data) >= MAX_KEYS:
            raise ValueError("Key capacity exceeded")
        clock = {}
        for version in self.siblings(key):
            for actor, count in version.clock:
                clock[actor] = max(clock.get(actor, 0), count)
        next_sequence = max(self.sequence, clock.get(self.replica_id, 0)) + 1
        clock[self.replica_id] = next_sequence
        version = Version(tuple(sorted(clock.items())), value)
        self._data[key] = (version,)
        self.sequence = next_sequence
        return version

    def delete(self, key):
        return self.put(key, None)

    def receive(self, records):
        """Validate and join a complete batch before mutating any local state."""
        incoming = parse_records(records)
        merged = dict(self._data)
        for key, versions in incoming.items():
            merged[key] = merge_versions(merged.get(key, ()), versions)
        if len(merged) > MAX_KEYS:
            raise ValueError("Key capacity exceeded")
        sequence = max([self.sequence] + [
            dict(v.clock).get(self.replica_id, 0) for group in incoming.values() for v in group
        ])
        self._data, self.sequence = merged, sequence

    def snapshot(self):
        return {"schema": 1, "replica_id": self.replica_id,
                "sequence": self.sequence, "records": self.records()}

    @classmethod
    def restore(cls, snapshot):
        if type(snapshot) is not dict or set(snapshot) != {"schema", "replica_id", "sequence", "records"}:
            raise ValueError("Invalid snapshot fields")
        if type(snapshot["schema"]) is not int or snapshot["schema"] != 1:
            raise ValueError("Unsupported snapshot schema")
        sequence = snapshot["sequence"]
        if type(sequence) is not int or not 0 <= sequence <= MAX_COUNTER:
            raise ValueError("Invalid snapshot sequence")
        replica = cls(snapshot["replica_id"])
        replica.receive(snapshot["records"])
        if sequence < replica.sequence:
            raise ValueError("Snapshot sequence precedes observed local clocks")
        replica.sequence = sequence
        return replica
