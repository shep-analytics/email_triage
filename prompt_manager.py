import json
import threading
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class PromptCriterion:
    """
    Represents a user-defined refinement that will be appended to the base prompt.
    """

    id: str
    text: str
    created_at: str
    updated_at: str
    enabled: bool = True
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        # Drop metadata when it's empty to keep the JSON tidy.
        if data.get("metadata") is None:
            data.pop("metadata", None)
        return data

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "PromptCriterion":
        return PromptCriterion(
            id=str(data["id"]),
            text=str(data["text"]),
            created_at=str(data.get("created_at") or _utc_now()),
            updated_at=str(data.get("updated_at") or _utc_now()),
            enabled=bool(data.get("enabled", True)),
            metadata=data.get("metadata"),
        )


class PromptManager:
    """
    Handles merging the base classification prompt with user-provided refinements.
    Persisted refinements allow the UI to add/edit/delete criteria that influence
    future LLM runs.
    """

    def __init__(self, base_prompt_path: Path, criteria_path: Optional[Path] = None) -> None:
        self.base_prompt_path = Path(base_prompt_path)
        if not self.base_prompt_path.exists():
            raise FileNotFoundError(f"Base prompt not found at {self.base_prompt_path.resolve()}")
        self.criteria_path = Path(criteria_path) if criteria_path else self.base_prompt_path.with_name("prompt_criteria.json")
        self._lock = threading.Lock()

    # ---------- Internal IO helpers ----------
    def _read_base_prompt(self) -> str:
        return self.base_prompt_path.read_text(encoding="utf-8").strip()

    def _load_records(self) -> List[PromptCriterion]:
        if not self.criteria_path.exists():
            return []
        try:
            raw = json.loads(self.criteria_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            # If the file is corrupted, fall back to an empty list but keep the file for inspection.
            return []
        if not isinstance(raw, list):
            return []
        records: List[PromptCriterion] = []
        for item in raw:
            if isinstance(item, dict) and "id" in item and "text" in item:
                try:
                    records.append(PromptCriterion.from_dict(item))
                except Exception:
                    continue
        return records

    def _write_records(self, records: Iterable[PromptCriterion]) -> None:
        serialised = [record.to_dict() for record in records]
        self.criteria_path.write_text(json.dumps(serialised, indent=2, sort_keys=True), encoding="utf-8")

    # ---------- Public API ----------
    def list_criteria(self) -> List[PromptCriterion]:
        with self._lock:
            return sorted(self._load_records(), key=lambda item: item.created_at)

    def get_criterion(self, criterion_id: str) -> PromptCriterion:
        with self._lock:
            for record in self._load_records():
                if record.id == criterion_id:
                    return record
        raise KeyError(f"Criterion {criterion_id} not found.")

    def add_criterion(self, text: str, *, metadata: Optional[Dict[str, Any]] = None) -> PromptCriterion:
        cleaned = text.strip()
        if not cleaned:
            raise ValueError("Criterion text must be a non-empty string.")
        with self._lock:
            records = self._load_records()
            criterion = PromptCriterion(
                id=uuid.uuid4().hex,
                text=cleaned,
                created_at=_utc_now(),
                updated_at=_utc_now(),
                enabled=True,
                metadata=metadata or None,
            )
            records.append(criterion)
            self._write_records(records)
            return criterion

    def update_criterion(self, criterion_id: str, text: str) -> PromptCriterion:
        cleaned = text.strip()
        if not cleaned:
            raise ValueError("Criterion text must be a non-empty string.")
        with self._lock:
            records = self._load_records()
            updated = None
            new_records: List[PromptCriterion] = []
            for record in records:
                if record.id == criterion_id:
                    record.text = cleaned
                    record.updated_at = _utc_now()
                    updated = record
                new_records.append(record)
            if updated is None:
                raise KeyError(f"Criterion {criterion_id} not found.")
            self._write_records(new_records)
            return updated

    def delete_criterion(self, criterion_id: str) -> None:
        with self._lock:
            records = self._load_records()
            new_records = [record for record in records if record.id != criterion_id]
            if len(new_records) == len(records):
                raise KeyError(f"Criterion {criterion_id} not found.")
            self._write_records(new_records)

    def toggle_criterion(self, criterion_id: str, *, enabled: bool) -> PromptCriterion:
        with self._lock:
            records = self._load_records()
            updated = None
            for record in records:
                if record.id == criterion_id:
                    record.enabled = enabled
                    record.updated_at = _utc_now()
                    updated = record
                    break
            if updated is None:
                raise KeyError(f"Criterion {criterion_id} not found.")
            self._write_records(records)
            return updated

    def build_classification_prompt(self) -> str:
        base = self._read_base_prompt()
        criteria_lines = self._formatted_criteria_lines()
        if not criteria_lines:
            return base
        return f"{base}\n\nAdditional user-specified criteria:\n" + "\n".join(f"- {line}" for line in criteria_lines)

    def formatted_criteria(self) -> str:
        lines = self._formatted_criteria_lines()
        return "\n".join(f"- {line}" for line in lines)

    def _formatted_criteria_lines(self) -> List[str]:
        criteria = [item for item in self.list_criteria() if item.enabled]
        return [item.text for item in criteria]

