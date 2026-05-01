from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum


class ViewRole(str, Enum):
    PLAYER = "player"
    ADMIN = "admin"
    DEBUG = "debug"
    AUDITOR = "auditor"


class NPCProfile(BaseModel):
    npc_id: str
    npc_template_id: str
    npc_name: str
    public_identity: Optional[str] = None
    hidden_identity: Optional[str] = None
    personality: Optional[str] = None
    speech_style: Optional[str] = None
    role_type: Optional[str] = None
    
    class Config:
        from_attributes = True


class NPCState(BaseModel):
    current_location_id: Optional[str] = None
    trust_score: int = 50
    suspicion_score: int = 0
    status_flags: Dict[str, Any] = Field(default_factory=dict)
    short_memory_summary: Optional[str] = None
    hidden_plan_state: Optional[str] = None
    
    class Config:
        from_attributes = True


class NPCBelief(BaseModel):
    belief_id: str
    subject: str
    belief_text: str
    confidence: float = 1.0
    source_event_id: Optional[str] = None
    created_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class NPCMemory(BaseModel):
    memory_id: str
    memory_type: str
    content: str
    importance_score: float = 0.5
    recency_score: float = 0.5
    source_event_id: Optional[str] = None
    created_at: Optional[datetime] = None
    is_private: bool = False
    
    class Config:
        from_attributes = True


class NPCGoal(BaseModel):
    goal_id: str
    goal_text: str
    priority: int = 0
    status: str = "active"
    progress: float = 0.0
    
    class Config:
        from_attributes = True


class NPCSecret(BaseModel):
    secret_id: str
    secret_type: str
    description: str
    is_revealed: bool = False
    revealed_to: List[str] = Field(default_factory=list)
    
    class Config:
        from_attributes = True


class NPCForbiddenKnowledge(BaseModel):
    knowledge_id: str
    knowledge_type: str
    description: str
    source: Optional[str] = None
    
    class Config:
        from_attributes = True


class NPCRecentContext(BaseModel):
    recent_memories: List[NPCMemory] = Field(default_factory=list)
    recent_interactions: List[Dict[str, Any]] = Field(default_factory=list)
    current_focus: Optional[str] = None
    emotional_state: Optional[str] = None
    
    class Config:
        from_attributes = True


class NPCMindView(BaseModel):
    npc_id: str
    session_id: str
    profile: NPCProfile
    state: NPCState
    beliefs: List[NPCBelief] = Field(default_factory=list)
    memories: List[NPCMemory] = Field(default_factory=list)
    private_memories: List[NPCMemory] = Field(default_factory=list)
    recent_context: NPCRecentContext
    goals: List[NPCGoal] = Field(default_factory=list)
    secrets: List[NPCSecret] = Field(default_factory=list)
    forbidden_knowledge: List[NPCForbiddenKnowledge] = Field(default_factory=list)
    secrets_metadata: Dict[str, Any] = Field(default_factory=dict)
    viewed_at: datetime = Field(default_factory=datetime.now)
    view_role: ViewRole = ViewRole.DEBUG
    
    class Config:
        from_attributes = True


class NPCMindViewer:
    REDACTED_TEXT = "[REDACTED - UNAUTHORIZED ACCESS]"
    
    def __init__(self, db_session=None):
        self.db = db_session
    
    def get_npc_mind(
        self,
        session_id: str,
        npc_id: str,
        view_role: ViewRole = ViewRole.DEBUG,
    ) -> Optional[NPCMindView]:
        if not self.db:
            return self._get_mock_mind_view(session_id, npc_id, view_role)
        
        from ..storage.models import SessionNPCStateModel, NPCTemplateModel
        
        npc_state = self.db.query(SessionNPCStateModel).filter(
            SessionNPCStateModel.session_id == session_id,
            SessionNPCStateModel.npc_template_id == npc_id
        ).first()
        
        if not npc_state:
            return None
        
        template = npc_state.npc_template
        
        profile = NPCProfile(
            npc_id=npc_state.id,
            npc_template_id=npc_state.npc_template_id,
            npc_name=template.name if template else "Unknown",
            public_identity=template.public_identity if template else None,
            hidden_identity=template.hidden_identity if template else None,
            personality=template.personality if template else None,
            speech_style=template.speech_style if template else None,
            role_type=template.role_type if template else None,
        )
        
        state = NPCState(
            current_location_id=npc_state.current_location_id,
            trust_score=npc_state.trust_score,
            suspicion_score=npc_state.suspicion_score,
            status_flags=npc_state.status_flags or {},
            short_memory_summary=npc_state.short_memory_summary,
            hidden_plan_state=npc_state.hidden_plan_state,
        )
        
        mind_view = NPCMindView(
            npc_id=npc_state.id,
            session_id=session_id,
            profile=profile,
            state=state,
            recent_context=NPCRecentContext(),
            view_role=view_role,
        )
        
        mind_view = self._apply_role_filtering(mind_view, view_role)
        
        return mind_view
    
    def _get_mock_mind_view(
        self,
        session_id: str,
        npc_id: str,
        view_role: ViewRole,
    ) -> NPCMindView:
        profile = NPCProfile(
            npc_id=f"npc_state_{npc_id}",
            npc_template_id=npc_id,
            npc_name="Test NPC",
            public_identity="A mysterious villager",
            hidden_identity="Secretly a demon lord in disguise",
            personality="Friendly but secretive",
            speech_style="Formal and polite",
            role_type="merchant",
        )
        
        state = NPCState(
            current_location_id="loc_village_square",
            trust_score=75,
            suspicion_score=10,
            status_flags={"is_merchant": True, "has_quest": True},
            short_memory_summary="Recently met the player, seems curious",
            hidden_plan_state="Planning to steal the artifact tonight",
        )
        
        beliefs = [
            NPCBelief(
                belief_id="belief_001",
                subject="player",
                belief_text="The player seems trustworthy",
                confidence=0.7,
                source_event_id="evt_001",
                created_at=datetime.now(),
            ),
            NPCBelief(
                belief_id="belief_002",
                subject="artifact",
                belief_text="The artifact is in the temple",
                confidence=0.9,
                source_event_id="evt_002",
                created_at=datetime.now(),
            ),
        ]
        
        memories = [
            NPCMemory(
                memory_id="mem_001",
                memory_type="episodic",
                content="Met the player at the village square",
                importance_score=0.6,
                recency_score=0.9,
                source_event_id="evt_001",
                created_at=datetime.now(),
                is_private=False,
            ),
            NPCMemory(
                memory_id="mem_002",
                memory_type="semantic",
                content="The player is looking for the artifact",
                importance_score=0.8,
                recency_score=0.8,
                source_event_id="evt_003",
                created_at=datetime.now(),
                is_private=False,
            ),
        ]
        
        private_memories = [
            NPCMemory(
                memory_id="mem_private_001",
                memory_type="secret",
                content="I am actually the demon lord",
                importance_score=1.0,
                recency_score=1.0,
                source_event_id="evt_secret",
                created_at=datetime.now(),
                is_private=True,
            ),
            NPCMemory(
                memory_id="mem_private_002",
                memory_type="secret",
                content="I plan to betray the player",
                importance_score=0.9,
                recency_score=0.9,
                source_event_id="evt_secret_002",
                created_at=datetime.now(),
                is_private=True,
            ),
        ]
        
        goals = [
            NPCGoal(
                goal_id="goal_001",
                goal_text="Obtain the artifact",
                priority=1,
                status="active",
                progress=0.3,
            ),
            NPCGoal(
                goal_id="goal_002",
                goal_text="Maintain disguise",
                priority=2,
                status="active",
                progress=0.8,
            ),
        ]
        
        secrets = [
            NPCSecret(
                secret_id="secret_001",
                secret_type="identity",
                description="True identity as demon lord",
                is_revealed=False,
                revealed_to=[],
            ),
            NPCSecret(
                secret_id="secret_002",
                secret_type="plan",
                description="Plan to betray the player",
                is_revealed=False,
                revealed_to=[],
            ),
        ]
        
        forbidden_knowledge = [
            NPCForbiddenKnowledge(
                knowledge_id="forbidden_001",
                knowledge_type="world_truth",
                description="The world is actually a simulation",
                source="ancient_texts",
            ),
            NPCForbiddenKnowledge(
                knowledge_id="forbidden_002",
                knowledge_type="future_event",
                description="The seal will break in 3 days",
                source="prophecy",
            ),
        ]
        
        recent_context = NPCRecentContext(
            recent_memories=memories[:2],
            recent_interactions=[
                {"turn": 1, "action": "greeted player"},
                {"turn": 2, "action": "offered quest"},
            ],
            current_focus="observing the player",
            emotional_state="curious",
        )
        
        mind_view = NPCMindView(
            npc_id=f"npc_state_{npc_id}",
            session_id=session_id,
            profile=profile,
            state=state,
            beliefs=beliefs,
            memories=memories,
            private_memories=private_memories,
            recent_context=recent_context,
            goals=goals,
            secrets=secrets,
            forbidden_knowledge=forbidden_knowledge,
            secrets_metadata={
                "total_secrets": len(secrets),
                "revealed_count": 0,
                "secret_types": ["identity", "plan"],
            },
            view_role=view_role,
        )
        
        return self._apply_role_filtering(mind_view, view_role)
    
    def _apply_role_filtering(
        self,
        mind_view: NPCMindView,
        view_role: ViewRole,
    ) -> NPCMindView:
        if view_role in [ViewRole.ADMIN, ViewRole.DEBUG]:
            return mind_view
        
        if view_role == ViewRole.PLAYER:
            mind_view.profile.hidden_identity = self.REDACTED_TEXT
            mind_view.state.hidden_plan_state = self.REDACTED_TEXT
            mind_view.private_memories = []
            mind_view.secrets = []
            mind_view.forbidden_knowledge = []
            mind_view.secrets_metadata = {
                "total_secrets": len(mind_view.secrets),
                "revealed_count": 0,
                "access_denied": True,
            }
        
        elif view_role == ViewRole.AUDITOR:
            mind_view.profile.hidden_identity = self.REDACTED_TEXT
            mind_view.state.hidden_plan_state = self.REDACTED_TEXT
            
            for memory in mind_view.private_memories:
                memory.content = self.REDACTED_TEXT
            
            for secret in mind_view.secrets:
                secret.description = self.REDACTED_TEXT
            
            for knowledge in mind_view.forbidden_knowledge:
                knowledge.description = self.REDACTED_TEXT
        
        return mind_view
    
    def can_view_mind(
        self,
        view_role: ViewRole,
    ) -> bool:
        return view_role in [ViewRole.ADMIN, ViewRole.DEBUG, ViewRole.AUDITOR]
    
    def list_session_npcs(
        self,
        session_id: str,
    ) -> List[Dict[str, Any]]:
        if not self.db:
            return [
                {"npc_id": "npc_001", "npc_name": "Test NPC 1", "role_type": "merchant"},
                {"npc_id": "npc_002", "npc_name": "Test NPC 2", "role_type": "villager"},
            ]
        
        from ..storage.models import SessionNPCStateModel, NPCTemplateModel
        
        npc_states = self.db.query(SessionNPCStateModel).filter(
            SessionNPCStateModel.session_id == session_id
        ).all()
        
        result = []
        for npc_state in npc_states:
            template = npc_state.npc_template
            result.append({
                "npc_id": npc_state.npc_template_id,
                "npc_name": template.name if template else "Unknown",
                "role_type": template.role_type if template else None,
                "current_location_id": npc_state.current_location_id,
                "trust_score": npc_state.trust_score,
            })
        
        return result
