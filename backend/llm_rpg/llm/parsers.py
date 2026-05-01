import json
import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class ParsedNPCAction(BaseModel):
    action_type: str
    target: Optional[str] = None
    summary: str
    confidence: float = 0.5
    hidden_motivation: Optional[str] = None


class ParsedNarration(BaseModel):
    text: str
    tone: str = "neutral"
    style_tags: List[str] = []
    hidden_info_leaked: bool = False


class ParsedWorldEvent(BaseModel):
    event_type: str
    description: str
    effects: Dict[str, Any] = {}
    importance: float = 0.5


class OutputParser:
    
    @staticmethod
    def parse_json(text: str) -> Optional[Dict[str, Any]]:
        try:
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass
        return None
    
    @staticmethod
    def parse_npc_action(text: str) -> ParsedNPCAction:
        data = OutputParser.parse_json(text)
        
        if data:
            return ParsedNPCAction(
                action_type=data.get("action_type", "idle"),
                target=data.get("target"),
                summary=data.get("summary", text),
                confidence=data.get("confidence", 0.5),
                hidden_motivation=data.get("hidden_motivation"),
            )
        
        return ParsedNPCAction(
            action_type="speak",
            summary=text,
            confidence=0.5,
        )
    
    @staticmethod
    def parse_narration(text: str, forbidden_info: List[str] = None) -> ParsedNarration:
        leaked = False
        if forbidden_info:
            for info in forbidden_info:
                if info.lower() in text.lower():
                    leaked = True
                    break
        
        return ParsedNarration(
            text=text,
            tone="neutral",
            hidden_info_leaked=leaked,
        )
    
    @staticmethod
    def parse_world_event(text: str) -> ParsedWorldEvent:
        data = OutputParser.parse_json(text)
        
        if data:
            return ParsedWorldEvent(
                event_type=data.get("event_type", "generic"),
                description=data.get("description", text),
                effects=data.get("effects", {}),
                importance=data.get("importance", 0.5),
            )
        
        return ParsedWorldEvent(
            event_type="generic",
            description=text,
        )
    
    @staticmethod
    def parse_list(text: str) -> List[str]:
        items = []
        
        lines = text.strip().split('\n')
        for line in lines:
            line = line.strip()
            if line.startswith('- '):
                items.append(line[2:])
            elif line.startswith('* '):
                items.append(line[2:])
            elif re.match(r'^\d+\.\s', line):
                items.append(re.sub(r'^\d+\.\s', '', line))
        
        if not items:
            items = [item.strip() for item in text.split(',') if item.strip()]
        
        return items
    
    @staticmethod
    def extract_json_array(text: str) -> List[Any]:
        try:
            array_match = re.search(r'\[.*\]', text, re.DOTALL)
            if array_match:
                return json.loads(array_match.group())
        except json.JSONDecodeError:
            pass
        return []
    
    @staticmethod
    def clean_narration(text: str) -> str:
        text = re.sub(r'\[.*?\]', '', text)
        text = re.sub(r'\{.*?\}', '', text)
        text = text.strip()
        return text