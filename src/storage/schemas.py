from dataclasses import dataclass


@dataclass(frozen=True)
class StoredObject:
    key: str
