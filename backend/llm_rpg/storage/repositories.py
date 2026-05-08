from datetime import datetime
from typing import Any, Dict, List, Optional, Type, TypeVar
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc

from .models import (
    WorldModel,
    ChapterModel,
    LocationModel,
    NPCTemplateModel,
    ItemTemplateModel,
    QuestTemplateModel,
    QuestStepModel,
    EventTemplateModel,
    PromptTemplateModel,
    UserModel,
    SystemSettingsModel,
    SaveSlotModel,
    SessionModel,
    SessionStateModel,
    SessionPlayerStateModel,
    SessionNPCStateModel,
    SessionInventoryItemModel,
    SessionQuestStateModel,
    SessionEventFlagModel,
    EventLogModel,
    MemorySummaryModel,
    MemoryFactModel,
    ModelCallLogModel,
    CombatSessionModel,
    CombatRoundModel,
    CombatActionModel,
    ScheduledEventModel,
    TurnTransactionModel,
    GameEventModel,
    StateDeltaModel,
    LLMStageResultModel,
    ValidationReportModel,
    NPCMemoryScopeModel,
    NPCBeliefModel,
    NPCPrivateMemoryModel,
    NPCSecretModel,
    NPCRelationshipMemoryModel,
)

T = TypeVar("T")


class BaseRepository:
    def __init__(self, db: Session, model: Type[T]):
        self.db = db
        self.model = model

    def create(self, data: Dict[str, Any]) -> T:
        instance = self.model(**data)
        self.db.add(instance)
        self.db.commit()
        self.db.refresh(instance)
        return instance

    def get_by_id(self, id: str) -> Optional[T]:
        return self.db.query(self.model).filter(self.model.id == id).first()

    def get_all(self, skip: int = 0, limit: int = 100) -> List[T]:
        return self.db.query(self.model).offset(skip).limit(limit).all()

    def update(self, id: str, data: Dict[str, Any]) -> Optional[T]:
        instance = self.get_by_id(id)
        if instance:
            for key, value in data.items():
                if hasattr(instance, key):
                    setattr(instance, key, value)
            self.db.commit()
            self.db.refresh(instance)
        return instance

    def delete(self, id: str) -> bool:
        instance = self.get_by_id(id)
        if instance:
            self.db.delete(instance)
            self.db.commit()
            return True
        return False


class WorldRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, WorldModel)

    def get_by_code(self, code: str) -> Optional[WorldModel]:
        return self.db.query(WorldModel).filter(WorldModel.code == code).first()

    def get_active(self) -> List[WorldModel]:
        return self.db.query(WorldModel).filter(WorldModel.status == "active").all()


class ChapterRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, ChapterModel)

    def get_by_world(self, world_id: str) -> List[ChapterModel]:
        return self.db.query(ChapterModel).filter(
            ChapterModel.world_id == world_id
        ).order_by(ChapterModel.chapter_no).all()

    def get_by_world_and_number(self, world_id: str, chapter_no: int) -> Optional[ChapterModel]:
        return self.db.query(ChapterModel).filter(
            and_(
                ChapterModel.world_id == world_id,
                ChapterModel.chapter_no == chapter_no
            )
        ).first()


class LocationRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, LocationModel)

    def get_by_world(self, world_id: str) -> List[LocationModel]:
        return self.db.query(LocationModel).filter(LocationModel.world_id == world_id).all()

    def get_by_chapter(self, chapter_id: str) -> List[LocationModel]:
        return self.db.query(LocationModel).filter(LocationModel.chapter_id == chapter_id).all()

    def get_by_code(self, world_id: str, code: str) -> Optional[LocationModel]:
        return self.db.query(LocationModel).filter(
            and_(
                LocationModel.world_id == world_id,
                LocationModel.code == code
            )
        ).first()


class NPCTemplateRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, NPCTemplateModel)

    def get_by_world(self, world_id: str) -> List[NPCTemplateModel]:
        return self.db.query(NPCTemplateModel).filter(NPCTemplateModel.world_id == world_id).all()

    def get_by_code(self, world_id: str, code: str) -> Optional[NPCTemplateModel]:
        return self.db.query(NPCTemplateModel).filter(
            and_(
                NPCTemplateModel.world_id == world_id,
                NPCTemplateModel.code == code
            )
        ).first()


class ItemTemplateRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, ItemTemplateModel)

    def get_by_world(self, world_id: str) -> List[ItemTemplateModel]:
        return self.db.query(ItemTemplateModel).filter(ItemTemplateModel.world_id == world_id).all()


class QuestTemplateRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, QuestTemplateModel)

    def get_by_world(self, world_id: str) -> List[QuestTemplateModel]:
        return self.db.query(QuestTemplateModel).filter(QuestTemplateModel.world_id == world_id).all()


class QuestStepRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, QuestStepModel)

    def get_by_quest(self, quest_template_id: str) -> List[QuestStepModel]:
        return self.db.query(QuestStepModel).filter(
            QuestStepModel.quest_template_id == quest_template_id
        ).order_by(QuestStepModel.step_no).all()


class EventTemplateRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, EventTemplateModel)

    def get_by_world(self, world_id: str) -> List[EventTemplateModel]:
        return self.db.query(EventTemplateModel).filter(
            or_(
                EventTemplateModel.world_id == world_id,
                EventTemplateModel.world_id.is_(None)
            )
        ).all()


class PromptTemplateRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, PromptTemplateModel)

    def get_by_type(self, prompt_type: str, world_id: Optional[str] = None) -> List[PromptTemplateModel]:
        query = self.db.query(PromptTemplateModel).filter(
            and_(
                PromptTemplateModel.prompt_type == prompt_type,
                PromptTemplateModel.enabled_flag == True
            )
        )
        if world_id:
            query = query.filter(
                or_(
                    PromptTemplateModel.world_id == world_id,
                    PromptTemplateModel.world_id.is_(None)
                )
            )
        return query.all()


class UserRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, UserModel)

    def get_by_username(self, username: str) -> Optional[UserModel]:
        return self.db.query(UserModel).filter(UserModel.username == username).first()

    def get_by_email(self, email: str) -> Optional[UserModel]:
        return self.db.query(UserModel).filter(UserModel.email == email).first()


class SaveSlotRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, SaveSlotModel)

    def get_by_user(self, user_id: str) -> List[SaveSlotModel]:
        return self.db.query(SaveSlotModel).filter(
            SaveSlotModel.user_id == user_id
        ).order_by(SaveSlotModel.slot_number).all()

    def get_by_user_and_slot(self, user_id: str, slot_number: int) -> Optional[SaveSlotModel]:
        return self.db.query(SaveSlotModel).filter(
            and_(
                SaveSlotModel.user_id == user_id,
                SaveSlotModel.slot_number == slot_number
            )
        ).first()


class SessionRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, SessionModel)

    def get_by_user(self, user_id: str) -> List[SessionModel]:
        return self.db.query(SessionModel).filter(
            SessionModel.user_id == user_id
        ).order_by(desc(SessionModel.last_played_at)).all()

    def get_active_by_user(self, user_id: str) -> List[SessionModel]:
        return self.db.query(SessionModel).filter(
            and_(
                SessionModel.user_id == user_id,
                SessionModel.status == "active"
            )
        ).all()

    def update_last_played(self, session_id: str) -> Optional[SessionModel]:
        from datetime import datetime
        return self.update(session_id, {"last_played_at": datetime.now()})


class SessionStateRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, SessionStateModel)

    def get_by_session(self, session_id: str) -> Optional[SessionStateModel]:
        return self.db.query(SessionStateModel).filter(
            SessionStateModel.session_id == session_id
        ).first()

    def create_or_update(self, data: Dict[str, Any]) -> SessionStateModel:
        existing = self.get_by_session(data["session_id"])
        if existing:
            return self.update(existing.id, data)
        return self.create(data)


class SessionPlayerStateRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, SessionPlayerStateModel)

    def get_by_session(self, session_id: str) -> Optional[SessionPlayerStateModel]:
        return self.db.query(SessionPlayerStateModel).filter(
            SessionPlayerStateModel.session_id == session_id
        ).first()

    def create_or_update(self, data: Dict[str, Any]) -> SessionPlayerStateModel:
        existing = self.get_by_session(data["session_id"])
        if existing:
            return self.update(existing.id, data)
        return self.create(data)


class SessionNPCStateRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, SessionNPCStateModel)

    def get_by_session(self, session_id: str) -> List[SessionNPCStateModel]:
        return self.db.query(SessionNPCStateModel).filter(
            SessionNPCStateModel.session_id == session_id
        ).all()

    def get_by_session_and_npc(self, session_id: str, npc_template_id: str) -> Optional[SessionNPCStateModel]:
        return self.db.query(SessionNPCStateModel).filter(
            and_(
                SessionNPCStateModel.session_id == session_id,
                SessionNPCStateModel.npc_template_id == npc_template_id
            )
        ).first()

    def create_or_update(self, data: Dict[str, Any]) -> SessionNPCStateModel:
        existing = self.get_by_session_and_npc(data["session_id"], data["npc_template_id"])
        if existing:
            return self.update(existing.id, data)
        return self.create(data)


class SessionInventoryItemRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, SessionInventoryItemModel)

    def get_by_session(self, session_id: str) -> List[SessionInventoryItemModel]:
        return self.db.query(SessionInventoryItemModel).filter(
            SessionInventoryItemModel.session_id == session_id
        ).all()

    def get_by_owner(self, session_id: str, owner_type: str, owner_ref_id: str) -> List[SessionInventoryItemModel]:
        return self.db.query(SessionInventoryItemModel).filter(
            and_(
                SessionInventoryItemModel.session_id == session_id,
                SessionInventoryItemModel.owner_type == owner_type,
                SessionInventoryItemModel.owner_ref_id == owner_ref_id
            )
        ).all()


class SessionQuestStateRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, SessionQuestStateModel)

    def get_by_session(self, session_id: str) -> List[SessionQuestStateModel]:
        return self.db.query(SessionQuestStateModel).filter(
            SessionQuestStateModel.session_id == session_id
        ).all()

    def get_by_session_and_quest(self, session_id: str, quest_template_id: str) -> Optional[SessionQuestStateModel]:
        return self.db.query(SessionQuestStateModel).filter(
            and_(
                SessionQuestStateModel.session_id == session_id,
                SessionQuestStateModel.quest_template_id == quest_template_id
            )
        ).first()


class SessionEventFlagRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, SessionEventFlagModel)

    def get_by_session(self, session_id: str) -> List[SessionEventFlagModel]:
        return self.db.query(SessionEventFlagModel).filter(
            SessionEventFlagModel.session_id == session_id
        ).all()

    def get_by_key(self, session_id: str, flag_key: str) -> Optional[SessionEventFlagModel]:
        return self.db.query(SessionEventFlagModel).filter(
            and_(
                SessionEventFlagModel.session_id == session_id,
                SessionEventFlagModel.flag_key == flag_key
            )
        ).first()

    def set_flag(self, session_id: str, flag_key: str, flag_value: str) -> SessionEventFlagModel:
        existing = self.get_by_key(session_id, flag_key)
        if existing:
            return self.update(existing.id, {"flag_value": flag_value})
        return self.create({
            "session_id": session_id,
            "flag_key": flag_key,
            "flag_value": flag_value
        })


class EventLogRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, EventLogModel)

    def get_by_session(self, session_id: str, skip: int = 0, limit: int = 100) -> List[EventLogModel]:
        return self.db.query(EventLogModel).filter(
            EventLogModel.session_id == session_id
        ).order_by(EventLogModel.turn_no).offset(skip).limit(limit).all()

    def get_by_turn(self, session_id: str, turn_no: int) -> List[EventLogModel]:
        return self.db.query(EventLogModel).filter(
            and_(
                EventLogModel.session_id == session_id,
                EventLogModel.turn_no == turn_no
            )
        ).all()

    def get_recent(self, session_id: str, limit: int = 10) -> List[EventLogModel]:
        return self.db.query(EventLogModel).filter(
            EventLogModel.session_id == session_id
        ).order_by(desc(EventLogModel.turn_no)).limit(limit).all()

    def get_by_session_ordered(self, session_id: str) -> List[EventLogModel]:
        return self.db.query(EventLogModel).filter(
            EventLogModel.session_id == session_id
        ).order_by(EventLogModel.turn_no.asc()).all()

    def get_by_session_turn_event(self, session_id: str, turn_no: int, event_type: str) -> Optional[EventLogModel]:
        return self.db.query(EventLogModel).filter(
            and_(
                EventLogModel.session_id == session_id,
                EventLogModel.turn_no == turn_no,
                EventLogModel.event_type == event_type
            )
        ).first()

    def ensure_initial_scene(self, session_id: str) -> EventLogModel:
        existing = self.get_by_session_turn_event(session_id, 0, "initial_scene")
        if existing:
            return existing
        
        from .models import generate_uuid
        initial_scene = self.create({
            "id": generate_uuid(),
            "session_id": session_id,
            "turn_no": 0,
            "event_type": "initial_scene",
            "input_text": None,
            "structured_action": None,
            "result_json": None,
            "narrative_text": "山门广场晨雾未散，青石阶上还残留着昨夜的露水。远处试炼堂的钟声缓缓响起，提醒你今日的修行试炼即将开始。你站在广场中央，试炼堂的朱门在薄雾后若隐若现。",
        })
        return initial_scene

    def create_or_get_player_turn(
        self, 
        session_id: str, 
        turn_no: int, 
        input_text: str, 
        narrative_text: str, 
        result_json: Optional[Dict] = None
    ) -> EventLogModel:
        existing = self.get_by_session_turn_event(session_id, turn_no, "player_turn")
        if existing:
            return existing
        
        from .models import generate_uuid
        player_turn = self.create({
            "id": generate_uuid(),
            "session_id": session_id,
            "turn_no": turn_no,
            "event_type": "player_turn",
            "input_text": input_text,
            "structured_action": None,
            "result_json": result_json,
            "narrative_text": narrative_text,
        })
        return player_turn


class MemorySummaryRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, MemorySummaryModel)

    def get_by_session(self, session_id: str) -> List[MemorySummaryModel]:
        return self.db.query(MemorySummaryModel).filter(
            MemorySummaryModel.session_id == session_id
        ).order_by(desc(MemorySummaryModel.importance_score)).all()

    def get_by_scope(self, session_id: str, scope_type: str, scope_ref_id: Optional[str] = None) -> List[MemorySummaryModel]:
        query = self.db.query(MemorySummaryModel).filter(
            and_(
                MemorySummaryModel.session_id == session_id,
                MemorySummaryModel.scope_type == scope_type
            )
        )
        if scope_ref_id:
            query = query.filter(MemorySummaryModel.scope_ref_id == scope_ref_id)
        return query.all()


class MemoryFactRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, MemoryFactModel)

    def get_by_session(self, session_id: str) -> List[MemoryFactModel]:
        return self.db.query(MemoryFactModel).filter(
            MemoryFactModel.session_id == session_id
        ).all()

    def get_by_type(self, session_id: str, fact_type: str) -> List[MemoryFactModel]:
        return self.db.query(MemoryFactModel).filter(
            and_(
                MemoryFactModel.session_id == session_id,
                MemoryFactModel.fact_type == fact_type
            )
        ).all()

    def get_by_subject(self, session_id: str, subject_ref: str) -> List[MemoryFactModel]:
        return self.db.query(MemoryFactModel).filter(
            and_(
                MemoryFactModel.session_id == session_id,
                MemoryFactModel.subject_ref == subject_ref
            )
        ).all()


class ModelCallLogRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, ModelCallLogModel)

    def get_by_session(self, session_id: str) -> List[ModelCallLogModel]:
        return self.db.query(ModelCallLogModel).filter(
            ModelCallLogModel.session_id == session_id
        ).order_by(ModelCallLogModel.turn_no).all()

    def get_total_cost(self, session_id: str) -> float:
        result = self.db.query(ModelCallLogModel).filter(
            ModelCallLogModel.session_id == session_id
        ).all()
        return sum(log.cost_estimate or 0 for log in result)
    
    def get_by_session_turn_prompttype(
        self,
        session_id: str,
        turn_no: Optional[int] = None,
        prompt_type: Optional[str] = None,
    ) -> List[ModelCallLogModel]:
        """
        Query model call logs by session_id, turn_no, and optional prompt_type.
        
        Args:
            session_id: Session ID to filter by
            turn_no: Optional turn number to filter by
            prompt_type: Optional prompt type to filter by
            
        Returns:
            List of matching ModelCallLogModel entries
        """
        query = self.db.query(ModelCallLogModel).filter(
            ModelCallLogModel.session_id == session_id
        )
        
        if turn_no is not None:
            query = query.filter(ModelCallLogModel.turn_no == turn_no)
        
        if prompt_type is not None:
            query = query.filter(ModelCallLogModel.prompt_type == prompt_type)
        
        return query.order_by(ModelCallLogModel.turn_no).all()


class CombatSessionRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, CombatSessionModel)

    def get_by_session(self, session_id: str) -> List[CombatSessionModel]:
        return self.db.query(CombatSessionModel).filter(
            CombatSessionModel.session_id == session_id
        ).order_by(desc(CombatSessionModel.started_at)).all()

    def get_active(self, session_id: str) -> Optional[CombatSessionModel]:
        return self.db.query(CombatSessionModel).filter(
            and_(
                CombatSessionModel.session_id == session_id,
                CombatSessionModel.combat_status == "active"
            )
        ).first()

    def update_status(self, combat_id: str, status: str, winner: Optional[str] = None) -> Optional[CombatSessionModel]:
        from datetime import datetime
        update_data = {
            "combat_status": status,
            "ended_at": datetime.now()
        }
        if winner:
            update_data["winner"] = winner
        return self.update(combat_id, update_data)


class CombatRoundRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, CombatRoundModel)

    def get_by_combat(self, combat_session_id: str) -> List[CombatRoundModel]:
        return self.db.query(CombatRoundModel).filter(
            CombatRoundModel.combat_session_id == combat_session_id
        ).order_by(CombatRoundModel.round_no).all()

    def get_current_round(self, combat_session_id: str) -> Optional[CombatRoundModel]:
        return self.db.query(CombatRoundModel).filter(
            CombatRoundModel.combat_session_id == combat_session_id
        ).order_by(desc(CombatRoundModel.round_no)).first()


class CombatActionRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, CombatActionModel)

    def get_by_round(self, combat_round_id: str) -> List[CombatActionModel]:
        return self.db.query(CombatActionModel).filter(
            CombatActionModel.combat_round_id == combat_round_id
        ).all()

    def get_by_actor(self, combat_round_id: str, actor_type: str, actor_ref_id: str) -> List[CombatActionModel]:
        return self.db.query(CombatActionModel).filter(
            and_(
                CombatActionModel.combat_round_id == combat_round_id,
                CombatActionModel.actor_type == actor_type,
                CombatActionModel.actor_ref_id == actor_ref_id
            )
        ).all()


class ScheduledEventRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, ScheduledEventModel)

    def get_by_session(self, session_id: str) -> List[ScheduledEventModel]:
        return self.db.query(ScheduledEventModel).filter(
            ScheduledEventModel.session_id == session_id
        ).all()

    def get_pending(self, session_id: str) -> List[ScheduledEventModel]:
        return self.db.query(ScheduledEventModel).filter(
            and_(
                ScheduledEventModel.session_id == session_id,
                ScheduledEventModel.status == "pending"
            )
        ).all()

    def mark_triggered(self, event_id: str) -> Optional[ScheduledEventModel]:
        return self.update(event_id, {"status": "triggered"})


class SystemSettingsRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, SystemSettingsModel)

    def get_singleton(self) -> SystemSettingsModel:
        settings = self.db.query(SystemSettingsModel).first()
        if not settings:
            settings = SystemSettingsModel()
            self.db.add(settings)
            self.db.commit()
            self.db.refresh(settings)
        return settings

    def update_singleton(self, data: Dict[str, Any], user_id: Optional[str] = None) -> SystemSettingsModel:
        settings = self.get_singleton()
        for key, value in data.items():
            if hasattr(settings, key):
                setattr(settings, key, value)
        if user_id:
            settings.updated_by_user_id = user_id
        self.db.commit()
        self.db.refresh(settings)
        return settings


class TurnTransactionRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, TurnTransactionModel)

    def get_by_session(self, session_id: str) -> List[TurnTransactionModel]:
        return self.db.query(TurnTransactionModel).filter(
            TurnTransactionModel.session_id == session_id
        ).order_by(TurnTransactionModel.turn_no).all()

    def get_by_session_and_turn(self, session_id: str, turn_no: int) -> Optional[TurnTransactionModel]:
        return self.db.query(TurnTransactionModel).filter(
            and_(
                TurnTransactionModel.session_id == session_id,
                TurnTransactionModel.turn_no == turn_no
            )
        ).first()

    def get_by_idempotency_key(self, idempotency_key: str) -> Optional[TurnTransactionModel]:
        return self.db.query(TurnTransactionModel).filter(
            TurnTransactionModel.idempotency_key == idempotency_key
        ).first()

    def update_status(
        self, 
        transaction_id: str, 
        status: str,
        error_json: Optional[Dict[str, Any]] = None,
        world_time_after: Optional[str] = None,
    ) -> Optional[TurnTransactionModel]:
        from datetime import datetime
        update_data: Dict[str, Any] = {"status": status}
        
        if status == "committed":
            update_data["committed_at"] = datetime.now()
            if world_time_after is not None:
                update_data["world_time_after"] = world_time_after
        elif status == "aborted":
            update_data["aborted_at"] = datetime.now()
            if error_json:
                update_data["error_json"] = error_json
        
        return self.update(transaction_id, update_data)


class GameEventRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, GameEventModel)

    def get_by_transaction(self, transaction_id: str) -> List[GameEventModel]:
        """Get all game events for a specific transaction."""
        return self.db.query(GameEventModel).filter(
            GameEventModel.transaction_id == transaction_id
        ).order_by(GameEventModel.occurred_at).all()

    def get_by_session(self, session_id: str, skip: int = 0, limit: int = 100) -> List[GameEventModel]:
        """Get all game events for a session, ordered by turn and time."""
        return self.db.query(GameEventModel).filter(
            GameEventModel.session_id == session_id
        ).order_by(GameEventModel.turn_no, GameEventModel.occurred_at).offset(skip).limit(limit).all()

    def get_by_type(
        self, 
        session_id: str, 
        event_type: str,
        skip: int = 0, 
        limit: int = 100
    ) -> List[GameEventModel]:
        """Get game events by type for a session."""
        return self.db.query(GameEventModel).filter(
            and_(
                GameEventModel.session_id == session_id,
                GameEventModel.event_type == event_type
            )
        ).order_by(GameEventModel.turn_no, GameEventModel.occurred_at).offset(skip).limit(limit).all()

    def get_by_session_and_turn(
        self, 
        session_id: str, 
        turn_no: int
    ) -> List[GameEventModel]:
        """Get all game events for a specific turn in a session."""
        return self.db.query(GameEventModel).filter(
            and_(
                GameEventModel.session_id == session_id,
                GameEventModel.turn_no == turn_no
            )
        ).order_by(GameEventModel.occurred_at).all()

    def get_by_visibility(
        self,
        session_id: str,
        visibility_scope: str,
        skip: int = 0,
        limit: int = 100
    ) -> List[GameEventModel]:
        """Get game events by visibility scope for a session."""
        return self.db.query(GameEventModel).filter(
            and_(
                GameEventModel.session_id == session_id,
                GameEventModel.visibility_scope == visibility_scope
            )
        ).order_by(GameEventModel.turn_no, GameEventModel.occurred_at).offset(skip).limit(limit).all()


class StateDeltaRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, StateDeltaModel)

    def get_by_transaction(self, transaction_id: str) -> List[StateDeltaModel]:
        """Get all state deltas for a specific transaction."""
        return self.db.query(StateDeltaModel).filter(
            StateDeltaModel.transaction_id == transaction_id
        ).order_by(StateDeltaModel.created_at).all()

    def get_by_session(self, session_id: str, skip: int = 0, limit: int = 100) -> List[StateDeltaModel]:
        """Get all state deltas for a session, ordered by turn and time."""
        return self.db.query(StateDeltaModel).filter(
            StateDeltaModel.session_id == session_id
        ).order_by(StateDeltaModel.turn_no, StateDeltaModel.created_at).offset(skip).limit(limit).all()

    def get_by_path(
        self,
        session_id: str,
        path: str,
        skip: int = 0,
        limit: int = 100
    ) -> List[StateDeltaModel]:
        """Get state deltas by path for a session."""
        return self.db.query(StateDeltaModel).filter(
            and_(
                StateDeltaModel.session_id == session_id,
                StateDeltaModel.path == path
            )
        ).order_by(StateDeltaModel.turn_no, StateDeltaModel.created_at).offset(skip).limit(limit).all()

    def get_by_session_and_turn(
        self,
        session_id: str,
        turn_no: int
    ) -> List[StateDeltaModel]:
        """Get all state deltas for a specific turn in a session."""
        return self.db.query(StateDeltaModel).filter(
            and_(
                StateDeltaModel.session_id == session_id,
                StateDeltaModel.turn_no == turn_no
            )
        ).order_by(StateDeltaModel.created_at).all()

    def get_by_source_event(self, source_event_id: str) -> List[StateDeltaModel]:
        """Get all state deltas for a specific source event."""
        return self.db.query(StateDeltaModel).filter(
            StateDeltaModel.source_event_id == source_event_id
        ).order_by(StateDeltaModel.created_at).all()


class LLMStageResultRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, LLMStageResultModel)

    def get_by_transaction(self, transaction_id: str) -> List[LLMStageResultModel]:
        """Get all LLM stage results for a specific transaction."""
        return self.db.query(LLMStageResultModel).filter(
            LLMStageResultModel.transaction_id == transaction_id
        ).order_by(LLMStageResultModel.created_at).all()

    def get_by_session(self, session_id: str, skip: int = 0, limit: int = 100) -> List[LLMStageResultModel]:
        """Get all LLM stage results for a session, ordered by turn and time."""
        return self.db.query(LLMStageResultModel).filter(
            LLMStageResultModel.session_id == session_id
        ).order_by(LLMStageResultModel.turn_no, LLMStageResultModel.created_at).offset(skip).limit(limit).all()

    def get_by_session_and_turn(
        self,
        session_id: str,
        turn_no: int
    ) -> List[LLMStageResultModel]:
        """Get all LLM stage results for a specific turn in a session."""
        return self.db.query(LLMStageResultModel).filter(
            and_(
                LLMStageResultModel.session_id == session_id,
                LLMStageResultModel.turn_no == turn_no
            )
        ).order_by(LLMStageResultModel.created_at).all()

    def get_by_stage(
        self,
        session_id: str,
        stage_name: str,
        skip: int = 0,
        limit: int = 100
    ) -> List[LLMStageResultModel]:
        """Get LLM stage results by stage name for a session."""
        return self.db.query(LLMStageResultModel).filter(
            and_(
                LLMStageResultModel.session_id == session_id,
                LLMStageResultModel.stage_name == stage_name
            )
        ).order_by(LLMStageResultModel.turn_no, LLMStageResultModel.created_at).offset(skip).limit(limit).all()

    def get_accepted_by_transaction(self, transaction_id: str) -> List[LLMStageResultModel]:
        """Get all accepted LLM stage results for a specific transaction."""
        return self.db.query(LLMStageResultModel).filter(
            and_(
                LLMStageResultModel.transaction_id == transaction_id,
                LLMStageResultModel.accepted == True
            )
        ).order_by(LLMStageResultModel.created_at).all()


class ValidationReportRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, ValidationReportModel)

    def get_by_transaction(self, transaction_id: str) -> List[ValidationReportModel]:
        """Get all validation reports for a specific transaction."""
        return self.db.query(ValidationReportModel).filter(
            ValidationReportModel.transaction_id == transaction_id
        ).order_by(ValidationReportModel.created_at).all()

    def get_by_session(self, session_id: str, skip: int = 0, limit: int = 100) -> List[ValidationReportModel]:
        """Get all validation reports for a session, ordered by turn and time."""
        return self.db.query(ValidationReportModel).filter(
            ValidationReportModel.session_id == session_id
        ).order_by(ValidationReportModel.turn_no, ValidationReportModel.created_at).offset(skip).limit(limit).all()

    def get_by_session_and_turn(
        self,
        session_id: str,
        turn_no: int
    ) -> List[ValidationReportModel]:
        """Get all validation reports for a specific turn in a session."""
        return self.db.query(ValidationReportModel).filter(
            and_(
                ValidationReportModel.session_id == session_id,
                ValidationReportModel.turn_no == turn_no
            )
        ).order_by(ValidationReportModel.created_at).all()

    def get_by_scope(
        self,
        session_id: str,
        scope: str,
        skip: int = 0,
        limit: int = 100
    ) -> List[ValidationReportModel]:
        """Get validation reports by scope for a session."""
        return self.db.query(ValidationReportModel).filter(
            and_(
                ValidationReportModel.session_id == session_id,
                ValidationReportModel.scope == scope
            )
        ).order_by(ValidationReportModel.turn_no, ValidationReportModel.created_at).offset(skip).limit(limit).all()

    def get_failed_by_session(self, session_id: str) -> List[ValidationReportModel]:
        """Get all failed validation reports for a session."""
        return self.db.query(ValidationReportModel).filter(
            and_(
                ValidationReportModel.session_id == session_id,
                ValidationReportModel.is_valid == False
            )
        ).order_by(ValidationReportModel.turn_no, ValidationReportModel.created_at).all()


class NPCMemoryScopeRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, NPCMemoryScopeModel)

    def get_by_session(self, session_id: str) -> List[NPCMemoryScopeModel]:
        return self.db.query(NPCMemoryScopeModel).filter(
            NPCMemoryScopeModel.session_id == session_id
        ).all()

    def get_by_session_and_npc(self, session_id: str, npc_id: str) -> Optional[NPCMemoryScopeModel]:
        return self.db.query(NPCMemoryScopeModel).filter(
            and_(
                NPCMemoryScopeModel.session_id == session_id,
                NPCMemoryScopeModel.npc_id == npc_id
            )
        ).first()

    def create_or_update(self, data: Dict[str, Any]) -> NPCMemoryScopeModel:
        existing = self.get_by_session_and_npc(data["session_id"], data["npc_id"])
        if existing:
            return self.update(existing.id, data)
        return self.create(data)


class NPCBeliefRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, NPCBeliefModel)

    def get_by_session(self, session_id: str) -> List[NPCBeliefModel]:
        return self.db.query(NPCBeliefModel).filter(
            NPCBeliefModel.session_id == session_id
        ).order_by(NPCBeliefModel.created_turn).all()

    def get_by_npc(self, session_id: str, npc_id: str) -> List[NPCBeliefModel]:
        return self.db.query(NPCBeliefModel).filter(
            and_(
                NPCBeliefModel.session_id == session_id,
                NPCBeliefModel.npc_id == npc_id
            )
        ).order_by(NPCBeliefModel.created_turn).all()

    def get_by_type(self, session_id: str, npc_id: str, belief_type: str) -> List[NPCBeliefModel]:
        return self.db.query(NPCBeliefModel).filter(
            and_(
                NPCBeliefModel.session_id == session_id,
                NPCBeliefModel.npc_id == npc_id,
                NPCBeliefModel.belief_type == belief_type
            )
        ).order_by(NPCBeliefModel.created_turn).all()


class NPCPrivateMemoryRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, NPCPrivateMemoryModel)

    def get_by_session(self, session_id: str) -> List[NPCPrivateMemoryModel]:
        return self.db.query(NPCPrivateMemoryModel).filter(
            NPCPrivateMemoryModel.session_id == session_id
        ).order_by(NPCPrivateMemoryModel.created_turn).all()

    def get_by_npc(self, session_id: str, npc_id: str) -> List[NPCPrivateMemoryModel]:
        return self.db.query(NPCPrivateMemoryModel).filter(
            and_(
                NPCPrivateMemoryModel.session_id == session_id,
                NPCPrivateMemoryModel.npc_id == npc_id
            )
        ).order_by(NPCPrivateMemoryModel.created_turn).all()

    def get_by_type(self, session_id: str, npc_id: str, memory_type: str) -> List[NPCPrivateMemoryModel]:
        return self.db.query(NPCPrivateMemoryModel).filter(
            and_(
                NPCPrivateMemoryModel.session_id == session_id,
                NPCPrivateMemoryModel.npc_id == npc_id,
                NPCPrivateMemoryModel.memory_type == memory_type
            )
        ).order_by(NPCPrivateMemoryModel.created_turn).all()

    def get_recent(self, session_id: str, npc_id: str, limit: int = 10) -> List[NPCPrivateMemoryModel]:
        return self.db.query(NPCPrivateMemoryModel).filter(
            and_(
                NPCPrivateMemoryModel.session_id == session_id,
                NPCPrivateMemoryModel.npc_id == npc_id
            )
        ).order_by(desc(NPCPrivateMemoryModel.created_turn)).limit(limit).all()

    def update_recall(self, memory_id: str, current_turn: int) -> Optional[NPCPrivateMemoryModel]:
        memory = self.get_by_id(memory_id)
        if memory:
            memory.recall_count += 1
            memory.last_accessed_turn = current_turn
            self.db.commit()
            self.db.refresh(memory)
        return memory


class NPCSecretRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, NPCSecretModel)

    def get_by_session(self, session_id: str) -> List[NPCSecretModel]:
        return self.db.query(NPCSecretModel).filter(
            NPCSecretModel.session_id == session_id
        ).order_by(NPCSecretModel.created_at).all()

    def get_by_npc(self, session_id: str, npc_id: str) -> List[NPCSecretModel]:
        return self.db.query(NPCSecretModel).filter(
            and_(
                NPCSecretModel.session_id == session_id,
                NPCSecretModel.npc_id == npc_id
            )
        ).order_by(NPCSecretModel.created_at).all()

    def get_by_status(self, session_id: str, npc_id: str, status: str) -> List[NPCSecretModel]:
        return self.db.query(NPCSecretModel).filter(
            and_(
                NPCSecretModel.session_id == session_id,
                NPCSecretModel.npc_id == npc_id,
                NPCSecretModel.status == status
            )
        ).order_by(NPCSecretModel.created_at).all()

    def update_status(self, secret_id: str, status: str) -> Optional[NPCSecretModel]:
        return self.update(secret_id, {"status": status})


class NPCRelationshipMemoryRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, NPCRelationshipMemoryModel)

    def get_by_session(self, session_id: str) -> List[NPCRelationshipMemoryModel]:
        return self.db.query(NPCRelationshipMemoryModel).filter(
            NPCRelationshipMemoryModel.session_id == session_id
        ).order_by(NPCRelationshipMemoryModel.created_turn).all()

    def get_by_npc(self, session_id: str, npc_id: str) -> List[NPCRelationshipMemoryModel]:
        return self.db.query(NPCRelationshipMemoryModel).filter(
            and_(
                NPCRelationshipMemoryModel.session_id == session_id,
                NPCRelationshipMemoryModel.npc_id == npc_id
            )
        ).order_by(NPCRelationshipMemoryModel.created_turn).all()

    def get_by_target(self, session_id: str, npc_id: str, target_id: str) -> List[NPCRelationshipMemoryModel]:
        return self.db.query(NPCRelationshipMemoryModel).filter(
            and_(
                NPCRelationshipMemoryModel.session_id == session_id,
                NPCRelationshipMemoryModel.npc_id == npc_id,
                NPCRelationshipMemoryModel.target_id == target_id
            )
        ).order_by(NPCRelationshipMemoryModel.created_turn).all()
