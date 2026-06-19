# ruff: noqa: E501
"""Planledger prompt profiles.

A prompt profile is an optional, project-configured policy that the
Planledger skill obeys. The CLI only parses, persists, and exposes the policy;
it never interviews the user itself. The coding agent asks the questions because
the Planledger skill tells it to.

The canonical profile is ``planning_workshop``; ``planning_interview`` is a deprecated alias.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Literal, cast

from planledger.models import Plan, Workspace

QuestionPolicy = Literal["ask_when_missing", "ask_one_at_a_time", "none"]
ActivationPolicy = Literal["always", "triggered"]

DEFAULT_PROFILE_NAME = "planning_workshop"
DEPRECATED_PROFILE_NAME = "planning_interview"
DEFAULT_MAX_REQUIRED_QUESTIONS = 20
DEFAULT_MIN_RESOLVED_REQUIRED_QUESTIONS_BEFORE_DONE = 0
_VALID_ACTIVATIONS = ("always", "triggered")
_VALID_QUESTION_POLICIES = ("ask_when_missing", "ask_one_at_a_time", "none")


@dataclass(frozen=True)
class PromptProfile:
    """Parsed representation of a configured prompt profile."""

    name: str
    enabled: bool = False
    active: bool = False
    activation: ActivationPolicy = "always"
    trigger_phrases: tuple[str, ...] = ()
    question_policy: QuestionPolicy = "ask_one_at_a_time"
    codebase_first: bool = True
    include_recommended_answer: bool = True
    max_required_questions: int = DEFAULT_MAX_REQUIRED_QUESTIONS
    min_resolved_required_questions_before_done: int = (
        DEFAULT_MIN_RESOLVED_REQUIRED_QUESTIONS_BEFORE_DONE
    )
    example_policy: str = "bdd_concrete_examples"
    min_examples_before_shaped: int = 1
    min_resolved_required_questions_before_shaped: int = 0
    required_question_topics: tuple[str, ...] = ()
    extra_guidance: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "active": self.active,
            "activation": self.activation,
            "trigger_phrases": list(self.trigger_phrases),
            "question_policy": self.question_policy,
            "codebase_first": self.codebase_first,
            "include_recommended_answer": self.include_recommended_answer,
            "max_required_questions": self.max_required_questions,
            "min_resolved_required_questions_before_done": (
                self.min_resolved_required_questions_before_done
            ),
            "required_question_topics": list(self.required_question_topics),
            "example_policy": self.example_policy,
            "min_examples_before_shaped": self.min_examples_before_shaped,
            "min_resolved_required_questions_before_shaped": self.min_resolved_required_questions_before_shaped,
            "extra_guidance": self.extra_guidance,
        }


def _disabled_profile(name: str) -> PromptProfile:
    return PromptProfile(name=name, enabled=False, active=False)


def _as_bool(value: Any) -> tuple[bool, str | None]:
    if isinstance(value, bool):
        return value, None
    return False, (f"prompt_profiles.{value!r} must be a boolean; treated as false.")


def _parse_prompt_profile(
    config: dict[str, Any], name: str
) -> tuple[PromptProfile, list[str]]:
    """Parse a prompt profile from config, returning profile and warnings.

    Missing or unknown blocks return a disabled profile. Invalid field values
    fall back to safe defaults and record a doctor warning.
    """
    warnings: list[str] = []
    profiles_section = config.get("prompt_profiles")
    if not isinstance(profiles_section, dict) or name not in profiles_section:
        if (
            name == DEFAULT_PROFILE_NAME
            and isinstance(profiles_section, dict)
            and DEPRECATED_PROFILE_NAME in profiles_section
        ):
            name = DEPRECATED_PROFILE_NAME
        else:
            return _disabled_profile(name), warnings

    raw = profiles_section[name]
    if not isinstance(raw, dict):
        warnings.append(
            f"prompt_profiles.{name} must be a table mapping; profile disabled."
        )
        return _disabled_profile(name), warnings

    enabled_value = raw.get("enabled", False)
    enabled, enabled_warning = _as_bool(enabled_value)
    if enabled_warning is not None:
        warnings.append(f"prompt_profiles.{name}.{enabled_warning}")

    # activation
    activation: ActivationPolicy = "always"
    raw_activation = raw.get("activation", "always")
    if isinstance(raw_activation, str) and raw_activation in _VALID_ACTIVATIONS:
        activation = cast("ActivationPolicy", raw_activation)
    else:
        warnings.append(
            f"prompt_profiles.{name}.activation must be one of "
            f"{list(_VALID_ACTIVATIONS)}; fell back to 'always'."
        )

    # question_policy
    question_policy: QuestionPolicy = "ask_one_at_a_time"
    raw_policy = raw.get("question_policy", "ask_one_at_a_time")
    if isinstance(raw_policy, str) and raw_policy in _VALID_QUESTION_POLICIES:
        question_policy = cast("QuestionPolicy", raw_policy)
    else:
        warnings.append(
            f"prompt_profiles.{name}.question_policy must be one of "
            f"{list(_VALID_QUESTION_POLICIES)}; fell back to 'ask_one_at_a_time'."
        )

    # codebase_first
    codebase_first = True
    raw_codebase_first = raw.get("codebase_first", True)
    if isinstance(raw_codebase_first, bool):
        codebase_first = raw_codebase_first
    elif "codebase_first" in raw:
        warnings.append(
            f"prompt_profiles.{name}.codebase_first must be a boolean; "
            "fell back to true."
        )

    # include_recommended_answer
    include_recommended_answer = True
    raw_include = raw.get("include_recommended_answer", True)
    if isinstance(raw_include, bool):
        include_recommended_answer = raw_include
    elif "include_recommended_answer" in raw:
        warnings.append(
            f"prompt_profiles.{name}.include_recommended_answer must be a boolean; "
            "fell back to true."
        )

    # max_required_questions (positive integer)
    max_required_questions = DEFAULT_MAX_REQUIRED_QUESTIONS
    raw_max = raw.get("max_required_questions", DEFAULT_MAX_REQUIRED_QUESTIONS)
    max_ok = isinstance(raw_max, int) and not isinstance(raw_max, bool)
    if not max_ok or raw_max <= 0:
        warnings.append(
            f"prompt_profiles.{name}.max_required_questions must be a positive "
            f"integer; fell back to {DEFAULT_MAX_REQUIRED_QUESTIONS}."
        )
    else:
        max_required_questions = raw_max

    # min_resolved_required_questions_before_done (zero or positive)
    min_resolved = DEFAULT_MIN_RESOLVED_REQUIRED_QUESTIONS_BEFORE_DONE
    raw_min = raw.get(
        "min_resolved_required_questions_before_done",
        DEFAULT_MIN_RESOLVED_REQUIRED_QUESTIONS_BEFORE_DONE,
    )
    if isinstance(raw_min, bool) or not isinstance(raw_min, int):
        warnings.append(
            f"prompt_profiles.{name}.min_resolved_required_questions_before_done "
            "must be zero or a positive integer; fell back to 0."
        )
    elif raw_min < 0:
        warnings.append(
            f"prompt_profiles.{name}.min_resolved_required_questions_before_done "
            "must be zero or a positive integer; fell back to 0."
        )
    else:
        min_resolved = raw_min

    example_policy = (
        str(raw.get("example_policy", "bdd_concrete_examples"))
        if isinstance(raw.get("example_policy", "bdd_concrete_examples"), str)
        else "bdd_concrete_examples"
    )
    min_examples_before_shaped = raw.get("min_examples_before_shaped", 1)
    if (
        isinstance(min_examples_before_shaped, bool)
        or not isinstance(min_examples_before_shaped, int)
        or min_examples_before_shaped < 0
    ):
        warnings.append(
            f"prompt_profiles.{name}.min_examples_before_shaped must be a non-negative integer; fell back to 1."
        )
        min_examples_before_shaped = 1
    min_resolved_required_questions_before_shaped = raw.get(
        "min_resolved_required_questions_before_shaped", 0
    )
    if (
        isinstance(min_resolved_required_questions_before_shaped, bool)
        or not isinstance(min_resolved_required_questions_before_shaped, int)
        or min_resolved_required_questions_before_shaped < 0
    ):
        warnings.append(
            f"prompt_profiles.{name}.min_resolved_required_questions_before_shaped must be a non-negative integer; fell back to 0."
        )
        min_resolved_required_questions_before_shaped = 0

    # trigger_phrases (array of strings)
    trigger_phrases: tuple[str, ...] = ()
    raw_phrases = raw.get("trigger_phrases", ())
    if isinstance(raw_phrases, list) and all(isinstance(p, str) for p in raw_phrases):
        trigger_phrases = tuple(raw_phrases)
    else:
        warnings.append(
            f"prompt_profiles.{name}.trigger_phrases must be an array of strings; "
            "ignored."
        )

    # required_question_topics (array of strings)
    required_topics: tuple[str, ...] = ()
    raw_topics = raw.get("required_question_topics", ())
    if isinstance(raw_topics, list) and all(isinstance(t, str) for t in raw_topics):
        required_topics = tuple(raw_topics)
    else:
        warnings.append(
            f"prompt_profiles.{name}.required_question_topics must be an array of "
            "strings; ignored."
        )

    # extra_guidance (string)
    extra_guidance = ""
    raw_guidance = raw.get("extra_guidance", "")
    if isinstance(raw_guidance, str):
        extra_guidance = raw_guidance
    else:
        warnings.append(
            f"prompt_profiles.{name}.extra_guidance must be a string; ignored."
        )

    profile = PromptProfile(
        name=name,
        enabled=enabled,
        active=False,
        activation=activation,
        trigger_phrases=trigger_phrases,
        question_policy=question_policy,
        codebase_first=codebase_first,
        include_recommended_answer=include_recommended_answer,
        max_required_questions=max_required_questions,
        min_resolved_required_questions_before_done=min_resolved,
        example_policy=example_policy,
        min_examples_before_shaped=min_examples_before_shaped,
        min_resolved_required_questions_before_shaped=min_resolved_required_questions_before_shaped,
        required_question_topics=required_topics,
        extra_guidance=extra_guidance,
    )
    return profile, warnings


def load_prompt_profile(
    config: dict[str, Any],
    name: str = DEFAULT_PROFILE_NAME,
    *,
    request_text: str = "",
) -> PromptProfile:
    """Load a prompt profile from config and resolve its active state.

    Returns a disabled profile when the block is missing or ``enabled = false``.
    For ``activation = "triggered"`` the profile is active only when
    ``request_text`` matches one of the configured trigger phrases
    (case-insensitive substring match).
    """
    profile, _warnings = _parse_prompt_profile(config, name)
    if not profile.enabled:
        return profile
    return replace(profile, active=_is_profile_active(profile, request_text))


def _is_profile_active(profile: PromptProfile, request_text: str) -> bool:
    if profile.activation == "always":
        return True
    if not profile.trigger_phrases:
        return False
    haystack = (request_text or "").lower()
    return any(phrase.lower() in haystack for phrase in profile.trigger_phrases)


def active_prompt_profile_for_plan(
    workspace: Workspace,
    plan: Plan,
    *,
    request_text: str | None = None,
) -> PromptProfile | None:
    """Return the active prompt profile for a plan, or None when inactive.

    When ``request_text`` is not supplied the plan ``request`` component is read
    via a lazy storage import to avoid an import cycle.
    """
    if request_text is None:
        from planledger.storage import load_component_content

        request_text = load_component_content(plan, "request")
    profile = load_prompt_profile(workspace.config, request_text=request_text)
    if not profile.enabled or not profile.active:
        return None
    return profile


def prompt_profile_doctor_warnings(
    config: dict[str, Any], name: str = DEFAULT_PROFILE_NAME
) -> list[str]:
    """Return doctor warnings for the configured prompt profile, if any."""
    _profile, warnings = _parse_prompt_profile(config, name)
    return warnings
