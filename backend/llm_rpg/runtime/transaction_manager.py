"""
Transaction Manager

Manages transaction boundaries for atomic operations.
Ensures ACID properties for game state changes.
"""

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Callable
from contextlib import contextmanager


class TransactionStatus(str, Enum):
    """Transaction status enum."""
    PENDING = "pending"
    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


class Transaction:
    """Represents a single transaction."""
    
    def __init__(self, transaction_id: str, game_id: str, operation: str):
        self.transaction_id = transaction_id
        self.game_id = game_id
        self.operation = operation
        self.status = TransactionStatus.PENDING
        self.created_at = datetime.now()
        self.committed_at: Optional[datetime] = None
        self.rolled_back_at: Optional[datetime] = None
        self.events: List[Dict[str, Any]] = []
        self.state_deltas: List[Dict[str, Any]] = []
        self.error: Optional[str] = None
    
    def add_event(self, event: Dict[str, Any]) -> None:
        """Add an event to the transaction."""
        self.events.append(event)
    
    def add_state_delta(self, delta: Dict[str, Any]) -> None:
        """Add a state delta to the transaction."""
        self.state_deltas.append(delta)
    
    def commit(self) -> None:
        """Mark transaction as committed."""
        self.status = TransactionStatus.COMMITTED
        self.committed_at = datetime.now()
    
    def rollback(self, error: Optional[str] = None) -> None:
        """Mark transaction as rolled back."""
        self.status = TransactionStatus.ROLLED_BACK
        self.rolled_back_at = datetime.now()
        self.error = error
    
    def fail(self, error: str) -> None:
        """Mark transaction as failed."""
        self.status = TransactionStatus.FAILED
        self.error = error
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert transaction to dictionary."""
        return {
            "transaction_id": self.transaction_id,
            "game_id": self.game_id,
            "operation": self.operation,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "committed_at": self.committed_at.isoformat() if self.committed_at else None,
            "rolled_back_at": self.rolled_back_at.isoformat() if self.rolled_back_at else None,
            "events_count": len(self.events),
            "state_deltas_count": len(self.state_deltas),
            "error": self.error,
        }


class TransactionManager:
    """
    Manages transaction boundaries for atomic game operations.
    
    Ensures:
    - Atomicity: All operations succeed or none do
    - Consistency: State remains valid after transaction
    - Isolation: Concurrent transactions don't interfere
    - Durability: Committed transactions persist
    """
    
    def __init__(self):
        self._active_transactions: Dict[str, Transaction] = {}
        self._transaction_history: List[Transaction] = []
        self._max_history_size = 100
    
    def begin_transaction(self, game_id: str, operation: str) -> Transaction:
        """
        Begin a new transaction.
        
        Args:
            game_id: The game ID
            operation: The operation being performed
            
        Returns:
            The new transaction
        """
        transaction_id = f"txn_{uuid.uuid4().hex[:12]}"
        transaction = Transaction(transaction_id, game_id, operation)
        self._active_transactions[transaction_id] = transaction
        return transaction
    
    def commit(self, transaction_id: str) -> bool:
        """
        Commit a transaction.
        
        Args:
            transaction_id: The transaction ID to commit
            
        Returns:
            True if committed successfully
        """
        transaction = self._active_transactions.get(transaction_id)
        if not transaction:
            return False
        
        transaction.commit()
        self._transaction_history.append(transaction)
        del self._active_transactions[transaction_id]
        self._cleanup_history()
        return True
    
    def rollback(self, transaction_id: str, error: Optional[str] = None) -> bool:
        """
        Rollback a transaction.
        
        Args:
            transaction_id: The transaction ID to rollback
            error: Optional error message
            
        Returns:
            True if rolled back successfully
        """
        transaction = self._active_transactions.get(transaction_id)
        if not transaction:
            return False
        
        transaction.rollback(error)
        self._transaction_history.append(transaction)
        del self._active_transactions[transaction_id]
        self._cleanup_history()
        return True
    
    def get_transaction(self, transaction_id: str) -> Optional[Transaction]:
        """Get a transaction by ID."""
        if transaction_id in self._active_transactions:
            return self._active_transactions[transaction_id]
        for txn in self._transaction_history:
            if txn.transaction_id == transaction_id:
                return txn
        return None
    
    def get_active_transactions(self, game_id: Optional[str] = None) -> List[Transaction]:
        """Get all active transactions, optionally filtered by game_id."""
        if game_id:
            return [txn for txn in self._active_transactions.values() if txn.game_id == game_id]
        return list(self._active_transactions.values())
    
    def get_transaction_history(self, game_id: Optional[str] = None, limit: int = 50) -> List[Transaction]:
        """Get transaction history, optionally filtered by game_id."""
        history = self._transaction_history
        if game_id:
            history = [txn for txn in history if txn.game_id == game_id]
        return history[-limit:]
    
    @contextmanager
    def transaction_scope(self, game_id: str, operation: str):
        """
        Context manager for transaction handling.
        
        Usage:
            with transaction_manager.transaction_scope(game_id, "move") as txn:
                # Perform operations
                transaction_manager.commit(txn.transaction_id)
        """
        transaction = self.begin_transaction(game_id, operation)
        try:
            yield transaction
            if transaction.status == TransactionStatus.PENDING:
                self.commit(transaction.transaction_id)
        except Exception as e:
            self.rollback(transaction.transaction_id, str(e))
            raise
    
    def _cleanup_history(self) -> None:
        """Clean up old transaction history."""
        if len(self._transaction_history) > self._max_history_size:
            self._transaction_history = self._transaction_history[-self._max_history_size:]
    
    def clear_history(self) -> None:
        """Clear all transaction history."""
        self._transaction_history.clear()
    
    def abort_all_active(self, game_id: Optional[str] = None) -> int:
        """Abort all active transactions, optionally filtered by game_id."""
        aborted = 0
        for txn_id, txn in list(self._active_transactions.items()):
            if game_id is None or txn.game_id == game_id:
                self.rollback(txn_id, "Aborted by system")
                aborted += 1
        return aborted
