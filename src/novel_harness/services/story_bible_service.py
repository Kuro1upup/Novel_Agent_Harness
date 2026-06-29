"""The sole application-level writer for story canon."""

from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy
from typing import Any

from sqlalchemy.orm import Session

from novel_harness.models import (
    CanonPatch,
    CharacterProfile,
    ForeshadowingItem,
    ForeshadowingProposal,
    StoryBible,
    TimelineEvent,
    WorldbuildingProposal,
)
from novel_harness.storage.repositories import (
    Repositories,
    ResourceNotFoundError,
    VersionConflictError,
)


class StoryBibleService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repositories = Repositories(session)

    def get(self, project_id: str) -> StoryBible:
        self.repositories.projects.require(project_id)
        bible = self.repositories.story_bibles.get_for_project(project_id)
        if bible is None:
            bible = StoryBible(project_id=project_id)
            self.repositories.story_bibles.add(bible)
        return bible

    def add_character(
        self,
        project_id: str,
        character: CharacterProfile | dict[str, Any],
        *,
        expected_version: int | None = None,
    ) -> StoryBible:
        bible = self.get(project_id)
        if expected_version is not None and bible.version != expected_version:
            raise VersionConflictError("Story Bible version changed")
        model = (
            character
            if isinstance(character, CharacterProfile)
            else CharacterProfile(project_id=project_id, **character)
        )
        if model.project_id != project_id:
            raise ValueError("character belongs to another project")
        if any(item.name == model.name for item in bible.characters):
            raise ValueError(f"character {model.name!r} already exists")
        updated = bible.model_copy(update={"characters": [*bible.characters, model]})
        self.repositories.characters.add(model)
        return self.repositories.story_bibles.update_versioned(
            updated, expected_version=bible.version
        )

    def add_foreshadowing(
        self,
        project_id: str,
        description: str,
        *,
        planted_at: str | None = None,
        expected_payoff: str | None = None,
        expected_version: int | None = None,
    ) -> StoryBible:
        bible = self.get(project_id)
        self._check_version(bible, expected_version)
        if not description.strip():
            raise ValueError("foreshadowing description is required")
        item = ForeshadowingItem(
            project_id=project_id,
            description=description.strip(),
            planted_at=planted_at,
            expected_payoff=expected_payoff,
            status="planted" if planted_at else "planned",
        )
        updated = bible.model_copy(
            update={"foreshadowing_items": [*bible.foreshadowing_items, item]}
        )
        return self.repositories.story_bibles.update_versioned(
            updated, expected_version=bible.version
        )

    def resolve_foreshadowing(
        self,
        project_id: str,
        item_id: str,
        *,
        resolution: str,
        expected_version: int | None = None,
    ) -> StoryBible:
        bible = self.get(project_id)
        self._check_version(bible, expected_version)
        if not resolution.strip():
            raise ValueError("foreshadowing resolution is required")
        items: list[ForeshadowingItem | dict[str, Any]] = []
        matched = False
        for raw in bible.foreshadowing_items:
            item = (
                raw if isinstance(raw, ForeshadowingItem) else ForeshadowingItem.model_validate(raw)
            )
            if item.id == item_id:
                item = item.model_copy(update={"status": "resolved"})
                matched = True
            items.append(item)
        if not matched:
            raise ResourceNotFoundError(f"foreshadowing item {item_id!r} was not found")
        updated = bible.model_copy(
            update={
                "foreshadowing_items": items,
                "resolved_threads": [*bible.resolved_threads, resolution.strip()],
            }
        )
        return self.repositories.story_bibles.update_versioned(
            updated, expected_version=bible.version
        )

    def add_rule(
        self,
        project_id: str,
        value: dict[str, Any] | str,
        *,
        expected_version: int | None = None,
    ) -> StoryBible:
        return self._append_entry(
            project_id,
            field="rules",
            value=value,
            expected_version=expected_version,
        )

    def add_faction(
        self,
        project_id: str,
        value: dict[str, Any],
        *,
        expected_version: int | None = None,
    ) -> StoryBible:
        if not isinstance(value, dict):
            raise ValueError("faction must be an object")
        return self._append_entry(
            project_id,
            field="factions",
            value=value,
            expected_version=expected_version,
        )

    def add_location(
        self,
        project_id: str,
        value: dict[str, Any],
        *,
        expected_version: int | None = None,
    ) -> StoryBible:
        if not isinstance(value, dict):
            raise ValueError("location must be an object")
        return self._append_entry(
            project_id,
            field="locations",
            value=value,
            expected_version=expected_version,
        )

    def add_timeline_event(
        self,
        project_id: str,
        event: TimelineEvent | dict[str, Any],
        *,
        expected_version: int | None = None,
    ) -> StoryBible:
        bible = self.get(project_id)
        self._check_version(bible, expected_version)
        model = (
            event
            if isinstance(event, TimelineEvent)
            else TimelineEvent(project_id=project_id, **event)
        )
        if model.project_id != project_id:
            raise ValueError("timeline event belongs to another project")
        updated = bible.model_copy(update={"timeline": [*bible.timeline, model]})
        return self.repositories.story_bibles.update_versioned(
            updated, expected_version=bible.version
        )

    def apply_worldbuilding(
        self,
        project_id: str,
        proposal: WorldbuildingProposal,
        *,
        expected_version: int | None = None,
    ) -> StoryBible:
        bible = self.get(project_id)
        self._check_version(bible, expected_version)
        updates = {
            "world_summary": proposal.world_summary or bible.world_summary,
            "rules": self._merge_entries(bible.rules, proposal.rules),
            "factions": self._merge_entries(bible.factions, proposal.factions),
            "locations": self._merge_entries(bible.locations, proposal.locations),
        }
        return self.repositories.story_bibles.update_versioned(
            bible.model_copy(update=updates),
            expected_version=bible.version,
        )

    def apply_foreshadowing(
        self,
        project_id: str,
        proposal: ForeshadowingProposal,
        *,
        expected_version: int | None = None,
    ) -> StoryBible:
        bible = self.get(project_id)
        self._check_version(bible, expected_version)
        existing_descriptions = {item.description for item in bible.foreshadowing_items}
        additions = [
            ForeshadowingItem(
                project_id=project_id,
                description=action.description,
                expected_payoff=action.target_payoff,
                status="planned",
            )
            for action in proposal.actions
            if action.action == "plant" and action.description not in existing_descriptions
        ]
        if not additions:
            return bible
        updated = bible.model_copy(
            update={"foreshadowing_items": [*bible.foreshadowing_items, *additions]}
        )
        return self.repositories.story_bibles.update_versioned(
            updated, expected_version=bible.version
        )

    def create_patch(
        self,
        project_id: str,
        draft_id: str,
        operations: list[dict[str, Any]],
    ) -> CanonPatch:
        bible = self.get(project_id)
        patch = CanonPatch(
            project_id=project_id,
            draft_id=draft_id,
            base_bible_version=bible.version,
            operations=operations,
        )
        self.repositories.canon_patches.add(patch)
        return patch

    def accept_patch(self, patch_id: str) -> StoryBible:
        patch = self.repositories.canon_patches.require(patch_id)
        if patch.status != "pending":
            raise ValueError(f"patch is already {patch.status}")
        bible = self.get(patch.project_id)
        if bible.version != patch.base_bible_version:
            raise VersionConflictError("Canon changed after the draft was generated")
        payload = bible.model_dump(mode="python")
        for operation in patch.operations:
            self._apply_operation(payload, operation, patch.project_id)
        updated = StoryBible.model_validate(payload)
        updated = self.repositories.story_bibles.update_versioned(
            updated, expected_version=bible.version
        )
        patch = patch.model_copy(
            update={
                "status": "accepted",
                "accepted_bible_version": updated.version,
            }
        )
        self.repositories.canon_patches.update(patch)
        draft = self.repositories.generations.get(patch.draft_id)
        if draft is not None:
            self.repositories.generations.update(draft.model_copy(update={"status": "accepted"}))
            chapter = self.repositories.manuscript_chapters.get_by_draft(draft.id)
            if chapter is not None and chapter.status == "drafting":
                self.repositories.manuscript_chapters.update(
                    chapter.model_copy(update={"status": "accepted"})
                )
        return updated

    def reject_patch(self, patch_id: str, *, reason: str = "") -> CanonPatch:
        patch = self.repositories.canon_patches.require(patch_id)
        if patch.status != "pending":
            raise ValueError(f"patch is already {patch.status}")
        metadata = [*patch.operations]
        if reason:
            metadata.append({"op": "rejection_note", "value": reason})
        rejected = patch.model_copy(update={"status": "rejected", "operations": metadata})
        return self.repositories.canon_patches.update(rejected)

    def _append_entry(
        self,
        project_id: str,
        *,
        field: str,
        value: dict[str, Any] | str,
        expected_version: int | None,
    ) -> StoryBible:
        bible = self.get(project_id)
        self._check_version(bible, expected_version)
        if isinstance(value, str) and not value.strip():
            raise ValueError(f"{field} entry must not be empty")
        current = list(getattr(bible, field))
        updated = bible.model_copy(update={field: [*current, deepcopy(value)]})
        return self.repositories.story_bibles.update_versioned(
            updated, expected_version=bible.version
        )

    @staticmethod
    def _check_version(bible: StoryBible, expected_version: int | None) -> None:
        if expected_version is not None and bible.version != expected_version:
            raise VersionConflictError("Story Bible version changed")

    @staticmethod
    def _merge_entries(
        current: Sequence[dict[str, Any] | str],
        proposed: Sequence[dict[str, Any] | str],
    ) -> list[dict[str, Any] | str]:
        merged = list(deepcopy(current))
        seen = {
            (str(item.get("name")) if isinstance(item, dict) and item.get("name") else str(item))
            for item in current
        }
        for item in proposed:
            identity = (
                str(item.get("name")) if isinstance(item, dict) and item.get("name") else str(item)
            )
            if identity not in seen:
                merged.append(deepcopy(item))
                seen.add(identity)
        return merged

    @staticmethod
    def _apply_operation(bible: dict[str, Any], operation: dict[str, Any], project_id: str) -> None:
        kind = operation.get("op")
        value = deepcopy(operation.get("value"))
        if kind == "add_character":
            bible["characters"].append(
                CharacterProfile(project_id=project_id, **(value or {})).model_dump()
            )
        elif kind == "add_timeline_event":
            bible["timeline"].append(
                TimelineEvent(project_id=project_id, **(value or {})).model_dump()
            )
        elif kind == "add_canon_event":
            bible["canon_events"].append(value)
        elif kind == "add_unresolved_thread":
            bible["unresolved_threads"].append(value)
        elif kind == "resolve_thread":
            bible["resolved_threads"].append(value)
        elif kind == "add_foreshadowing":
            bible["foreshadowing_items"].append(
                ForeshadowingItem(project_id=project_id, **(value or {})).model_dump()
            )
        else:
            raise ValueError(f"unsupported canon operation: {kind!r}")
