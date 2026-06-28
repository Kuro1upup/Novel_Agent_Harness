"""The sole application-level writer for story canon."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from sqlalchemy.orm import Session

from novel_harness.models import (
    CanonPatch,
    CharacterProfile,
    ForeshadowingItem,
    StoryBible,
    TimelineEvent,
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
    ) -> StoryBible:
        bible = self.get(project_id)
        item = ForeshadowingItem(
            project_id=project_id,
            description=description,
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
    ) -> StoryBible:
        bible = self.get(project_id)
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
                "resolved_threads": [*bible.resolved_threads, resolution],
            }
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
        return updated

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
