"""Rule-first story continuity checking."""

from __future__ import annotations

import re
from typing import Any

from novel_harness.models.generation import ContinuityIssue
from novel_harness.models.story_bible import StoryBible

from ._base import as_dict, call_provider, format_prompt, load_prompt, make_model


def _chinese_number(value: str) -> int | None:
    if value.isdigit():
        return int(value)
    digits = {
        "零": 0,
        "〇": 0,
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    if value == "十":
        return 10
    if "十" in value:
        left, right = value.split("十", 1)
        tens = digits.get(left, 1) if left else 1
        ones = digits.get(right, 0) if right else 0
        return tens * 10 + ones
    if all(char in digits for char in value):
        return int("".join(str(digits[char]) for char in value))
    return None


class ContinuityChecker:
    def __init__(self, llm_provider: Any | None = None) -> None:
        self.llm_provider = llm_provider

    @staticmethod
    def _issue(
        project_id: str,
        category: str,
        description: str,
        evidence: str,
        suggestion: str,
        severity: str = "warning",
    ) -> ContinuityIssue:
        return make_model(
            ContinuityIssue,
            {
                "project_id": project_id,
                "category": category,
                "severity": severity,
                "description": description,
                "evidence": evidence,
                "suggestion": suggestion,
            },
        )

    def check(
        self,
        draft: str,
        story_bible: StoryBible,
        *,
        project_id: str | None = None,
    ) -> list[ContinuityIssue]:
        if not draft.strip():
            raise ValueError("draft is required")
        project_id = project_id or story_bible.project_id
        issues: list[ContinuityIssue] = []

        for character in story_bible.characters:
            character_data = as_dict(character)
            name = str(character_data.get("name", ""))
            age_value = character_data.get("age")
            if not name or name not in draft:
                continue
            if isinstance(age_value, int):
                age_values = re.findall(
                    rf"{re.escape(name)}(?:今年|已经|才)*[，,\s]*"
                    r"(\d{1,3}|[零〇一二两三四五六七八九十]{1,4})\s*岁",
                    draft,
                )
                ages = {
                    parsed for value in age_values if (parsed := _chinese_number(value)) is not None
                }
                for age in sorted(ages):
                    if age != age_value:
                        issues.append(
                            self._issue(
                                project_id,
                                "character",
                                f"{name}的年龄与人物设定冲突",
                                f"设定为 {age_value} 岁，草稿写为 {age} 岁",
                                f"改为 {age_value} 岁，或先更新 Story Bible 并解释时间变化。",
                                "error",
                            )
                        )
            for constraint in character_data.get("constraints", []):
                forbidden = re.search(r"(?:不能|不得|不会|从不|禁止)(.+)", constraint)
                if forbidden:
                    phrase = forbidden.group(1).strip("，。；; ")
                    if len(phrase) >= 2 and phrase in draft:
                        issues.append(
                            self._issue(
                                project_id,
                                "character",
                                f"{name}可能违反人物约束",
                                f"约束“{constraint}”，草稿出现“{phrase}”",
                                "重写该行动，或补充足以改变人物选择的触发事件。",
                            )
                        )

        for rule in story_bible.rules:
            data = as_dict(rule)
            text = (
                str(rule)
                if isinstance(rule, str)
                else str(data.get("description") or data.get("rule") or data.get("name") or "")
            )
            forbidden = re.search(r"(?:不能|不得|禁止|不存在)(.+)", text)
            if forbidden:
                phrase = forbidden.group(1).strip("，。；; ")
                if 2 <= len(phrase) <= 30 and phrase in draft:
                    issues.append(
                        self._issue(
                            project_id,
                            "world_rule",
                            "草稿可能违反世界规则",
                            f"规则“{text}”，草稿出现“{phrase}”",
                            "遵守既有规则，或把例外的条件、代价和来源作为显式剧情。",
                            "error",
                        )
                    )

        canon_text = "\n".join(str(item) for item in story_bible.canon_events)
        for character in story_bible.characters:
            character_name = str(as_dict(character).get("name", ""))
            if (
                character_name
                and re.search(rf"{re.escape(character_name)}.*(?:死亡|已死|身亡)", canon_text)
                and re.search(
                    rf"{re.escape(character_name)}(?:说|问|答|走|跑|笑|看|拿|推)",
                    draft,
                )
            ):
                issues.append(
                    self._issue(
                        project_id,
                        "timeline",
                        f"已死亡人物 {character_name} 在草稿中直接行动",
                        "Story Bible 的 canon_events 记录其死亡",
                        "改为回忆、转述或删除该行动；若复活，必须先建立符合规则的因果链。",
                        "error",
                    )
                )

        planted = []
        for item in story_bible.foreshadowing_items:
            data = as_dict(item)
            if data.get("status") == "planted":
                planted.append(str(data.get("description", "")))
        if planted and not any(item and item in draft for item in planted):
            issues.append(
                self._issue(
                    project_id,
                    "foreshadowing",
                    "本章未触及任何已埋伏笔",
                    f"当前已埋伏笔共 {len(planted)} 项",
                    "若本章处于相关剧情线，可用动作或环境细节轻微强化；否则可忽略。",
                    "info",
                )
            )
        return issues

    async def acheck(self, *args: Any, **kwargs: Any) -> list[ContinuityIssue]:
        baseline = self.check(*args, **kwargs)
        if self.llm_provider is None:
            return baseline
        prompt = format_prompt(
            load_prompt("continuity_checker"),
            {
                "draft": args[0] if args else kwargs.get("draft"),
                "story_bible": args[1] if len(args) > 1 else kwargs.get("story_bible"),
                "rule_based_issues": baseline,
            },
        )
        try:
            result = await call_provider(self.llm_provider, prompt=prompt)
            rows = result.get("issues", []) if isinstance(result, dict) else []
            bible = args[1] if len(args) > 1 else kwargs.get("story_bible")
            project_id = kwargs.get("project_id") or getattr(bible, "project_id", "default")
            llm_issues = [
                ContinuityIssue.model_validate({"project_id": project_id, **row}) for row in rows
            ]
            return baseline + llm_issues
        except Exception:
            return baseline

    async def run(self, *args: Any, **kwargs: Any) -> list[ContinuityIssue]:
        return await self.acheck(*args, **kwargs)
