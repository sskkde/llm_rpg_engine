import json

from llm_rpg.llm.parsers import OutputParser
from llm_rpg.api.turn_output import finalize_turn_output


def test_parse_narration_extracts_recommended_actions_from_json():
    payload = json.dumps({
        "text": "你站在山门广场，晨雾正在散去。",
        "recommended_actions": ["环顾四周", "前往试炼堂"],
    }, ensure_ascii=False)

    parsed = OutputParser.parse_narration(payload)

    assert parsed.text == "你站在山门广场，晨雾正在散去。"
    assert parsed.recommended_actions == ["环顾四周", "前往试炼堂"]


def test_parse_narration_removes_inline_action_prompt_text():
    parsed = OutputParser.parse_narration("雾气在石阶上流动。请选择你的行动：环顾四周 / 前进")

    assert parsed.text == "雾气在石阶上流动。"
    assert parsed.recommended_actions == []


def test_parse_narration_removes_prompt_lines_only():
    parsed = OutputParser.parse_narration("雾气在石阶上流动。\n推荐行动：环顾四周 / 前进")

    assert parsed.text == "雾气在石阶上流动。"
    assert parsed.recommended_actions == []


def test_parse_narration_preserves_valid_choice_prose():
    parsed = OutputParser.parse_narration("你可以选择沿山路前进，也可以先停下观察雾色。")

    assert parsed.text == "你可以选择沿山路前进，也可以先停下观察雾色。"


def test_parse_narration_filters_recommended_actions_with_forbidden_info():
    payload = json.dumps({
        "text": "师姐站在雾中，神情平静。",
        "recommended_actions": ["询问师姐", "揭穿玄冥密令"],
    }, ensure_ascii=False)

    parsed = OutputParser.parse_narration(payload, forbidden_info=["玄冥密令"])

    assert parsed.text == "师姐站在雾中，神情平静。"
    assert parsed.recommended_actions == []
    assert parsed.hidden_info_leaked is True


def test_finalize_turn_output_filters_forbidden_recommended_actions():
    payload = json.dumps({
        "text": "你听见试炼堂中传来钟声。",
        "recommended_actions": ["前往试炼堂", "追问禁忌真相"],
    }, ensure_ascii=False)

    narration, recommended_actions = finalize_turn_output(payload, forbidden_info=["禁忌真相"])

    assert narration == "你听见试炼堂中传来钟声。"
    assert recommended_actions == []


def test_parse_narration_sanitizes_forbidden_text():
    parsed = OutputParser.parse_narration("玄冥密令藏在钟声里。", forbidden_info=["玄冥密令"])

    assert parsed.text == "...藏在钟声里。"
    assert parsed.hidden_info_leaked is True
