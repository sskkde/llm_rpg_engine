from typing import Any, Dict, List, Optional, Tuple

from ..llm.parsers import OutputParser


def normalize_recommended_actions(actions: Optional[List[Any]]) -> List[str]:
    if not actions:
        return []

    normalized = []
    for action in actions:
        text = str(action).strip()
        if text and text not in normalized:
            normalized.append(text)
    return normalized[:4]


def finalize_turn_output(narration: str, forbidden_info: Optional[List[str]] = None) -> Tuple[str, List[str]]:
    parsed = OutputParser.parse_narration(narration, forbidden_info=forbidden_info)
    recommended_actions = normalize_recommended_actions(parsed.recommended_actions)
    return parsed.text, recommended_actions


def recommended_actions_from_result(result_json: Optional[Dict[str, Any]]) -> List[str]:
    if not isinstance(result_json, dict):
        return []
    return normalize_recommended_actions(result_json.get("recommended_actions"))
