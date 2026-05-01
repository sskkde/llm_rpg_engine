from typing import Any, Dict, List, Optional, Tuple
import math

from ..models.common import MemoryQuery, RetrievalResult, TimeRange
from ..models.memories import Memory
from ..models.summaries import Summary
from ..models.lore import LoreEntry, LoreView
from ..models.perspectives import (
    Perspective, WorldPerspective, PlayerPerspective, NPCPerspective, NarratorPerspective,
    VisibilityLevel, VisibilityResult
)


class RetrievalSystem:
    """
    Hybrid retrieval system combining multiple filtering and scoring strategies.

    Filters applied (in order):
    1. Entity filter - only memories involving specified entities
    2. Time filter - within specified turn range
    3. Importance filter - above threshold
    4. Semantic similarity - embedding-based (with pgvector fallback)
    5. Perspective filter - based on what the viewer knows
    6. Visibility filter - entity-based visibility
    7. State-consistency filter - ensure consistency with current state
    """

    def __init__(self):
        self._memory_index: Dict[str, Memory] = {}
        self._summary_index: Dict[str, Summary] = {}
        self._lore_index: Dict[str, LoreEntry] = {}
        self._embeddings: Dict[str, List[float]] = {}  # Fallback storage for embeddings

    def index_memory(self, memory: Memory, embedding: Optional[List[float]] = None) -> None:
        """Index a memory with optional embedding vector."""
        self._memory_index[memory.memory_id] = memory
        if embedding:
            self._embeddings[memory.memory_id] = embedding

    def index_summary(self, summary: Summary, embedding: Optional[List[float]] = None) -> None:
        """Index a summary with optional embedding vector."""
        self._summary_index[summary.summary_id] = summary
        if embedding:
            self._embeddings[summary.summary_id] = embedding

    def index_lore(self, lore: LoreEntry, embedding: Optional[List[float]] = None) -> None:
        """Index lore with optional embedding vector."""
        self._lore_index[lore.lore_id] = lore
        if embedding:
            self._embeddings[lore.lore_id] = embedding

    def _compute_cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """Compute cosine similarity between two vectors."""
        if not vec1 or not vec2 or len(vec1) != len(vec2):
            return 0.0

        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = math.sqrt(sum(a * a for a in vec1))
        norm2 = math.sqrt(sum(b * b for b in vec2))

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot_product / (norm1 * norm2)

    def _compute_text_similarity(self, query: str, content: str) -> float:
        """Compute simple text-based similarity score."""
        if not query or not content:
            return 0.0

        query_lower = query.lower()
        content_lower = content.lower()

        # Exact match bonus
        if query_lower == content_lower:
            return 1.0

        # Substring match
        if query_lower in content_lower:
            return 0.5 + 0.3 * (len(query_lower) / len(content_lower))

        # Word overlap
        query_words = set(query_lower.split())
        content_words = set(content_lower.split())

        if not query_words or not content_words:
            return 0.0

        overlap = len(query_words & content_words)
        return 0.2 * (overlap / len(query_words))

    def _compute_semantic_score(
        self,
        memory: Memory,
        query: MemoryQuery,
    ) -> float:
        """Compute semantic similarity score between memory and query."""
        # Try embedding-based similarity first (pgvector or stored)
        if query.query_text:
            # Check if we have embeddings stored
            query_embedding = self._embeddings.get(f"query:{query.query_text}")
            memory_embedding = self._embeddings.get(memory.memory_id)

            if query_embedding and memory_embedding:
                return self._compute_cosine_similarity(query_embedding, memory_embedding)

            # Fallback to text similarity
            return self._compute_text_similarity(query.query_text, memory.content)

        return 0.5  # Default neutral score

    def apply_entity_filter(
        self,
        memories: List[Memory],
        entity_ids: Optional[List[str]],
    ) -> List[Memory]:
        """Filter memories by entity involvement."""
        if not entity_ids:
            return memories

        filtered = []
        for memory in memories:
            # Memory is included if it involves ANY of the specified entities
            memory_entities = set(memory.entities)
            query_entities = set(entity_ids)

            if memory_entities & query_entities:  # Intersection
                filtered.append(memory)

        return filtered

    def apply_time_filter(
        self,
        memories: List[Memory],
        time_range: Optional[TimeRange],
    ) -> List[Memory]:
        """Filter memories by time range."""
        if not time_range:
            return memories

        filtered = []
        for memory in memories:
            if memory.created_turn < time_range.start_turn:
                continue
            if memory.created_turn > time_range.end_turn:
                continue
            filtered.append(memory)

        return filtered

    def apply_importance_filter(
        self,
        memories: List[Memory],
        threshold: float,
    ) -> List[Memory]:
        """Filter memories by importance threshold."""
        return [m for m in memories if m.importance >= threshold]

    def apply_memory_type_filter(
        self,
        memories: List[Memory],
        memory_types: Optional[List[str]],
    ) -> List[Memory]:
        """Filter memories by type."""
        if not memory_types:
            return memories

        return [m for m in memories if m.memory_type in memory_types]

    def apply_owner_filter(
        self,
        memories: List[Memory],
        owner_id: Optional[str],
        owner_type: Optional[str],
    ) -> List[Memory]:
        """Filter memories by owner."""
        filtered = memories

        if owner_id:
            filtered = [m for m in filtered if m.owner_id == owner_id]

        if owner_type:
            filtered = [m for m in filtered if m.owner_type == owner_type]

        return filtered

    def retrieve_memories(self, query: MemoryQuery) -> List[RetrievalResult]:
        """
        Retrieve memories using hybrid scoring.

        Scoring weights:
        - Importance: 0.25
        - Current strength: 0.20
        - Emotional weight: 0.10
        - Entity match: 0.25
        - Semantic similarity: 0.20
        """
        # Start with all memories
        candidates = list(self._memory_index.values())

        # Apply filters in order
        candidates = self.apply_owner_filter(candidates, query.owner_id, query.owner_type)
        candidates = self.apply_memory_type_filter(candidates, query.memory_types)
        candidates = self.apply_importance_filter(candidates, query.importance_threshold)
        candidates = self.apply_time_filter(candidates, query.time_range)
        candidates = self.apply_entity_filter(candidates, query.entity_ids)

        # Score remaining candidates
        results = []
        for memory in candidates:
            score = self._compute_memory_score(memory, query)
            results.append(RetrievalResult(
                memory_id=memory.memory_id,
                content=memory.content,
                score=score,
                source="memory",
                metadata={
                    "memory_type": memory.memory_type,
                    "importance": memory.importance,
                    "emotional_weight": memory.emotional_weight,
                    "confidence": memory.confidence,
                    "current_strength": memory.current_strength,
                    "entities": memory.entities,
                    "created_turn": memory.created_turn,
                },
            ))

        # Sort by score and limit
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:query.limit]

    def _compute_memory_score(self, memory: Memory, query: MemoryQuery) -> float:
        """Compute hybrid score for a memory."""
        score = 0.0

        # Importance (0.25)
        score += memory.importance * 0.25

        # Current strength (0.20)
        score += memory.current_strength * 0.20

        # Emotional weight (0.10) - use absolute value
        score += abs(memory.emotional_weight) * 0.10

        # Entity match (0.25)
        if query.entity_ids:
            memory_entities = set(memory.entities)
            query_entities = set(query.entity_ids)
            matching = len(memory_entities & query_entities)
            if matching > 0:
                score += (matching / len(query_entities)) * 0.25

        # Semantic similarity (0.20)
        semantic_score = self._compute_semantic_score(memory, query)
        score += semantic_score * 0.20

        return min(1.0, score)

    def apply_perspective_filter(
        self,
        results: List[RetrievalResult],
        perspective: Perspective,
    ) -> List[RetrievalResult]:
        """
        Filter results based on perspective knowledge.

        WorldPerspective: sees everything
        PlayerPerspective: sees known_facts and known_rumors
        NPCPerspective: sees known_facts, believed_rumors, and secrets
        """
        if isinstance(perspective, WorldPerspective):
            return results

        filtered = []

        for result in results:
            # Get visibility level for this result
            visibility = self._check_result_visibility(result, perspective)

            if visibility == VisibilityLevel.FULL:
                filtered.append(result)
            elif visibility == VisibilityLevel.RUMOR:
                # Mark as rumor and reduce score
                result.metadata["is_rumor"] = True
                result.metadata["confidence"] = 0.5
                result.score *= 0.8
                filtered.append(result)
            # HIDDEN results are excluded

        return filtered

    def _check_result_visibility(
        self,
        result: RetrievalResult,
        perspective: Perspective,
    ) -> VisibilityLevel:
        """Check visibility level of a result for a perspective."""
        if isinstance(perspective, WorldPerspective):
            return VisibilityLevel.FULL

        content_id = result.memory_id

        if isinstance(perspective, PlayerPerspective):
            if content_id in perspective.known_facts:
                return VisibilityLevel.FULL
            if content_id in perspective.known_rumors:
                return VisibilityLevel.RUMOR
            return VisibilityLevel.HIDDEN

        if isinstance(perspective, NPCPerspective):
            if content_id in perspective.known_facts:
                return VisibilityLevel.FULL
            if content_id in perspective.believed_rumors:
                return VisibilityLevel.RUMOR
            if content_id in perspective.secrets:
                return VisibilityLevel.FULL
            if content_id in perspective.forbidden_knowledge:
                return VisibilityLevel.HIDDEN
            return VisibilityLevel.HIDDEN

        if isinstance(perspective, NarratorPerspective):
            # Narrator uses base perspective (usually PlayerPerspective)
            # and also respects forbidden_info
            if content_id in perspective.forbidden_info:
                return VisibilityLevel.HIDDEN
            return VisibilityLevel.FULL

        return VisibilityLevel.HIDDEN

    def apply_visibility_filter(
        self,
        results: List[RetrievalResult],
        visible_entity_ids: List[str],
    ) -> List[RetrievalResult]:
        """
        Filter results based on entity visibility.
        Only memories involving visible entities are included.
        """
        if not visible_entity_ids:
            return results

        filtered = []
        visible_set = set(visible_entity_ids)

        for result in results:
            if result.source == "memory":
                memory = self._memory_index.get(result.memory_id)
                if memory:
                    memory_entities = set(memory.entities)
                    if memory_entities & visible_set:  # Intersection
                        filtered.append(result)
            else:
                # Non-memory results pass through
                filtered.append(result)

        return filtered

    def apply_state_consistency_filter(
        self,
        results: List[RetrievalResult],
        current_state: Dict[str, Any],
    ) -> List[RetrievalResult]:
        """
        Filter results to ensure consistency with current state.

        This prevents outdated summaries from overriding canonical state.
        For example, if an NPC has moved to a new location, don't include
        memories of them being at the old location unless recent enough.
        """
        if not current_state:
            return results

        current_turn = current_state.get("current_turn", 0)
        filtered = []

        for result in results:
            # Check if this is an outdated memory
            created_turn = result.metadata.get("created_turn", 0)

            # Memories from more than 5 turns ago might be outdated
            # unless they have high importance or are about permanent facts
            age = current_turn - created_turn

            if age > 5 and result.source == "memory":
                importance = result.metadata.get("importance", 0.5)
                if importance < 0.7:
                    # Mark as potentially outdated but don't filter
                    result.metadata["potentially_outdated"] = True
                    result.score *= 0.7  # Reduce score

            filtered.append(result)

        return filtered

    def retrieve_summaries(
        self,
        turn_range: Optional[TimeRange] = None,
        summary_type: Optional[str] = None,
        owner_id: Optional[str] = None,
        limit: int = 10,
    ) -> List[RetrievalResult]:
        """Retrieve summaries with filtering."""
        candidates = []

        for summary in self._summary_index.values():
            if turn_range:
                if summary.end_turn < turn_range.start_turn:
                    continue
                if summary.start_turn > turn_range.end_turn:
                    continue
            if summary_type and summary.summary_type != summary_type:
                continue
            if owner_id and summary.owner_id != owner_id:
                continue

            score = summary.importance
            candidates.append(RetrievalResult(
                memory_id=summary.summary_id,
                content=summary.content,
                score=score,
                source="summary",
                metadata={
                    "summary_type": summary.summary_type,
                    "start_turn": summary.start_turn,
                    "end_turn": summary.end_turn,
                },
            ))

        candidates.sort(key=lambda r: r.score, reverse=True)
        return candidates[:limit]

    def retrieve_lore(
        self,
        query: str = "",
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        perspective: Optional[Perspective] = None,
        limit: int = 10,
    ) -> List[LoreView]:
        """
        Retrieve lore entries with optional perspective filtering.

        If perspective is provided, returns LoreView objects with appropriate
        content based on what the perspective knows.
        """
        candidates = []

        for lore in self._lore_index.values():
            if category and lore.category != category:
                continue
            if tags:
                if not any(tag in lore.tags for tag in tags):
                    continue

            score = 0.0

            if query:
                query_lower = query.lower()
                if query_lower in lore.title.lower():
                    score += 0.5
                if query_lower in lore.canonical_content.lower():
                    score += 0.3
                for tag in lore.tags:
                    if query_lower in tag.lower():
                        score += 0.1

            if tags:
                matching_tags = set(tags) & set(lore.tags)
                score += len(matching_tags) / len(tags) * 0.2

            candidates.append((lore, score))

        # Sort by score
        candidates.sort(key=lambda x: x[1], reverse=True)
        candidates = candidates[:limit]

        # Apply perspective filtering if provided
        if perspective:
            return self._filter_lore_for_perspective(candidates, perspective)

        # Return full views
        return [
            LoreView(
                lore_id=lore.lore_id,
                title=lore.title,
                category=lore.category,
                content=lore.canonical_content,
                visibility_level="full",
                perspective_id="world",
            )
            for lore, _ in candidates
        ]

    def _filter_lore_for_perspective(
        self,
        candidates: List[Tuple[LoreEntry, float]],
        perspective: Perspective,
    ) -> List[LoreView]:
        """Filter lore entries for a specific perspective."""
        views = []

        for entry, score in candidates:
            if isinstance(perspective, WorldPerspective):
                views.append(LoreView(
                    lore_id=entry.lore_id,
                    title=entry.title,
                    category=entry.category,
                    content=entry.canonical_content,
                    visibility_level="full",
                    perspective_id=perspective.perspective_id,
                ))

            elif isinstance(perspective, PlayerPerspective):
                if entry.lore_id in perspective.known_facts:
                    views.append(LoreView(
                        lore_id=entry.lore_id,
                        title=entry.title,
                        category=entry.category,
                        content=entry.canonical_content,
                        visibility_level="full",
                        perspective_id=perspective.perspective_id,
                    ))
                elif entry.lore_id in perspective.known_rumors:
                    rumor_content = entry.rumor_versions[0] if entry.rumor_versions else entry.public_content
                    views.append(LoreView(
                        lore_id=entry.lore_id,
                        title=entry.title,
                        category=entry.category,
                        content=rumor_content or "",
                        visibility_level="rumor",
                        perspective_id=perspective.perspective_id,
                        is_rumor=True,
                        confidence=0.5,
                    ))
                elif entry.public_content:
                    views.append(LoreView(
                        lore_id=entry.lore_id,
                        title=entry.title,
                        category=entry.category,
                        content=entry.public_content,
                        visibility_level="partial",
                        perspective_id=perspective.perspective_id,
                    ))

            elif isinstance(perspective, NPCPerspective):
                if entry.lore_id in perspective.known_facts:
                    views.append(LoreView(
                        lore_id=entry.lore_id,
                        title=entry.title,
                        category=entry.category,
                        content=entry.canonical_content,
                        visibility_level="full",
                        perspective_id=perspective.perspective_id,
                    ))
                elif entry.lore_id in perspective.believed_rumors:
                    rumor_content = entry.rumor_versions[0] if entry.rumor_versions else entry.public_content
                    views.append(LoreView(
                        lore_id=entry.lore_id,
                        title=entry.title,
                        category=entry.category,
                        content=rumor_content or "",
                        visibility_level="rumor",
                        perspective_id=perspective.perspective_id,
                        is_rumor=True,
                        confidence=0.5,
                    ))
                elif entry.public_content:
                    views.append(LoreView(
                        lore_id=entry.lore_id,
                        title=entry.title,
                        category=entry.category,
                        content=entry.public_content,
                        visibility_level="partial",
                        perspective_id=perspective.perspective_id,
                    ))

        return views

    def hybrid_retrieve(
        self,
        query: MemoryQuery,
        perspective: Optional[Perspective] = None,
        visible_entity_ids: Optional[List[str]] = None,
        current_state: Optional[Dict[str, Any]] = None,
    ) -> List[RetrievalResult]:
        """
        Perform hybrid retrieval with all filters.

        Filter order:
        1. Entity filter
        2. Time filter
        3. Importance filter
        4. Semantic similarity scoring
        5. Perspective filter
        6. Visibility filter
        7. State-consistency filter
        """
        # Step 1-4: Retrieve memories with hybrid scoring
        results = self.retrieve_memories(query)

        # Step 5: Apply perspective filter
        if perspective:
            results = self.apply_perspective_filter(results, perspective)

        # Step 6: Apply visibility filter
        if visible_entity_ids:
            results = self.apply_visibility_filter(results, visible_entity_ids)

        # Step 7: Apply state-consistency filter
        if current_state:
            results = self.apply_state_consistency_filter(results, current_state)

        return results

    def store_embedding(self, content_id: str, embedding: List[float]) -> None:
        """Store embedding vector for a content item (fallback for pgvector)."""
        self._embeddings[content_id] = embedding

    def get_embedding(self, content_id: str) -> Optional[List[float]]:
        """Retrieve embedding vector for a content item."""
        return self._embeddings.get(content_id)
