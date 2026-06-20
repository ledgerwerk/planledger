from __future__ import annotations

from planledger.prompt_profiles import (
    DEFAULT_MAX_REQUIRED_QUESTIONS,
    DEFAULT_PROFILE_NAME,
    load_prompt_profile,
    prompt_profile_doctor_warnings,
)


def test_missing_profile_is_disabled() -> None:
    profile = load_prompt_profile({})
    assert profile.name == DEFAULT_PROFILE_NAME
    assert profile.enabled is False
    assert profile.active is False
    assert profile.activation == "always"


def test_missing_profile_doctor_warnings_empty() -> None:
    assert prompt_profile_doctor_warnings({}) == []


def test_planning_interview_profile_parses_enabled_config() -> None:
    config = {
        "prompt_profiles": {
            "planning_interview": {
                "enabled": True,
                "activation": "always",
                "question_policy": "ask_one_at_a_time",
                "codebase_first": True,
                "include_recommended_answer": True,
                "max_required_questions": 20,
                "min_resolved_required_questions_before_done": 0,
                "trigger_phrases": ["grill me"],
                "required_question_topics": ["scope", "tests"],
                "extra_guidance": "Interview the user about the plan.",
            }
        }
    }
    profile = load_prompt_profile(config)
    assert profile.enabled is True
    assert profile.activation == "always"
    assert profile.question_policy == "ask_one_at_a_time"
    assert profile.max_required_questions == 20
    assert profile.min_resolved_required_questions_before_done == 0
    assert profile.trigger_phrases == ("grill me",)
    assert profile.required_question_topics == ("scope", "tests")
    assert profile.extra_guidance == "Interview the user about the plan."
    data = profile.to_dict()
    assert data["name"] == "planning_interview"
    assert data["enabled"] is True
    assert data["trigger_phrases"] == ["grill me"]
    assert data["required_question_topics"] == ["scope", "tests"]
    assert prompt_profile_doctor_warnings(config) == []


def test_planning_interview_always_activation_is_active() -> None:
    config = {
        "prompt_profiles": {
            "planning_interview": {"enabled": True, "activation": "always"}
        }
    }
    profile = load_prompt_profile(config, request_text="anything")
    assert profile.enabled is True
    assert profile.active is True


def test_planning_interview_triggered_activation_matches_request_text() -> None:
    config = {
        "prompt_profiles": {
            "planning_interview": {
                "enabled": True,
                "activation": "triggered",
                "trigger_phrases": ["grill me", "challenge this plan"],
            }
        }
    }
    matching = load_prompt_profile(config, request_text="Please grill me on this plan.")
    assert matching.enabled is True
    assert matching.active is True
    case_variants = load_prompt_profile(
        config, request_text="CHALLENGE THIS PLAN please"
    )
    assert case_variants.active is True


def test_planning_interview_triggered_activation_ignores_non_matching_request() -> None:
    config = {
        "prompt_profiles": {
            "planning_interview": {
                "enabled": True,
                "activation": "triggered",
                "trigger_phrases": ["grill me"],
            }
        }
    }
    profile = load_prompt_profile(config, request_text="Just plan feature A.")
    assert profile.enabled is True
    assert profile.active is False


def test_planning_interview_triggered_without_phrases_is_inactive() -> None:
    config = {
        "prompt_profiles": {
            "planning_interview": {"enabled": True, "activation": "triggered"}
        }
    }
    profile = load_prompt_profile(config, request_text="grill me")
    assert profile.enabled is True
    assert profile.active is False


def test_disabled_profile_is_inactive_even_when_always() -> None:
    config = {
        "prompt_profiles": {
            "planning_interview": {"enabled": False, "activation": "always"}
        }
    }
    profile = load_prompt_profile(config)
    assert profile.enabled is False
    assert profile.active is False


def test_invalid_profile_values_report_doctor_warnings() -> None:
    config = {
        "prompt_profiles": {
            "planning_interview": {
                "enabled": True,
                "activation": "sometimes",
                "question_policy": "rapid_fire",
                "codebase_first": "yes",
                "include_recommended_answer": "no",
                "max_required_questions": 0,
                "min_resolved_required_questions_before_done": -1,
                "trigger_phrases": "grill me",
                "required_question_topics": ["scope", 5],
                "extra_guidance": ["not a string"],
            }
        }
    }
    warnings = prompt_profile_doctor_warnings(config)
    # Every malformed field must produce at least one warning.
    joined = "\n".join(warnings)
    assert "activation" in joined
    assert "question_policy" in joined
    assert "codebase_first" in joined
    assert "include_recommended_answer" in joined
    assert "max_required_questions" in joined
    assert "min_resolved_required_questions_before_done" in joined
    assert "trigger_phrases" in joined
    assert "required_question_topics" in joined
    assert "extra_guidance" in joined
    # The parsed profile still falls back to safe defaults.
    profile = load_prompt_profile(config)
    assert profile.enabled is True
    assert profile.activation == "always"
    assert profile.question_policy == "ask_one_at_a_time"
    assert profile.max_required_questions == DEFAULT_MAX_REQUIRED_QUESTIONS
    assert profile.min_resolved_required_questions_before_done == 0
    assert profile.trigger_phrases == ()
    assert profile.required_question_topics == ()
    assert profile.extra_guidance == ""


def test_unknown_profile_names_are_ignored_unless_requested() -> None:
    config = {
        "prompt_profiles": {"other_profile": {"enabled": True, "activation": "always"}}
    }
    default = load_prompt_profile(config)
    assert default.enabled is False
    requested = load_prompt_profile(config, name="other_profile")
    assert requested.enabled is True
    assert requested.active is True


def test_non_table_profile_block_is_disabled_with_warning() -> None:
    config = {"prompt_profiles": {"planning_interview": "enabled"}}
    profile = load_prompt_profile(config)
    assert profile.enabled is False
    warnings = prompt_profile_doctor_warnings(config)
    assert any("must be a table mapping" in w for w in warnings)


def test_required_topics_are_exposed_in_profile_payload() -> None:
    config = {
        "prompt_profiles": {
            "planning_workshop": {
                "enabled": True,
                "activation": "always",
                "required_question_topics": ["scope", "tests", "rollback", "risks"],
                "max_required_questions": 12,
                "min_resolved_required_questions_before_done": 1,
            }
        }
    }
    profile = load_prompt_profile(config, request_text="shape a feature")
    assert profile.enabled is True
    assert profile.active is True
    payload = profile.to_dict()
    assert payload["required_question_topics"] == [
        "scope",
        "tests",
        "rollback",
        "risks",
    ]
    assert payload["max_required_questions"] == 12
    assert payload["min_resolved_required_questions_before_done"] == 1
