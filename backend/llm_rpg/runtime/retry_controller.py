"""
Retry Controller

Manages retry logic for failed operations with exponential backoff.
Provides configurable retry policies and circuit breaker patterns.
"""

import time
import random
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple, Type, Union
from functools import wraps


class RetryPolicy(str, Enum):
    """Retry policy types."""
    FIXED = "fixed"
    EXPONENTIAL = "exponential"
    LINEAR = "linear"


class CircuitState(str, Enum):
    """Circuit breaker states."""
    CLOSED = "closed"  # Normal operation
    OPEN = "open"      # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing if recovered


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""
    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    policy: RetryPolicy = RetryPolicy.EXPONENTIAL
    retryable_exceptions: Tuple[Type[Exception], ...] = (Exception,)
    on_retry_callback: Optional[Callable[[int, Exception], None]] = None
    on_exhausted_callback: Optional[Callable[[Exception], None]] = None


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker."""
    failure_threshold: int = 5
    recovery_timeout: float = 30.0
    half_open_max_calls: int = 3


class RetryStats:
    """Statistics for retry operations."""
    
    def __init__(self):
        self.total_attempts = 0
        self.successful_attempts = 0
        self.failed_attempts = 0
        self.retried_operations = 0
        self.circuit_opened = 0
        self.circuit_closed = 0
    
    def record_attempt(self, success: bool) -> None:
        """Record an attempt."""
        self.total_attempts += 1
        if success:
            self.successful_attempts += 1
        else:
            self.failed_attempts += 1
    
    def record_retry(self) -> None:
        """Record a retry operation."""
        self.retried_operations += 1
    
    def record_circuit_open(self) -> None:
        """Record circuit opening."""
        self.circuit_opened += 1
    
    def record_circuit_close(self) -> None:
        """Record circuit closing."""
        self.circuit_closed += 1
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert stats to dictionary."""
        return {
            "total_attempts": self.total_attempts,
            "successful_attempts": self.successful_attempts,
            "failed_attempts": self.failed_attempts,
            "retried_operations": self.retried_operations,
            "circuit_opened": self.circuit_opened,
            "circuit_closed": self.circuit_closed,
            "success_rate": (
                self.successful_attempts / self.total_attempts
                if self.total_attempts > 0 else 0.0
            ),
        }


class CircuitBreaker:
    """Circuit breaker for fault tolerance."""
    
    def __init__(self, name: str, config: CircuitBreakerConfig):
        self.name = name
        self.config = config
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[float] = None
        self.half_open_calls = 0
    
    def can_execute(self) -> bool:
        """Check if operation can execute."""
        if self.state == CircuitState.CLOSED:
            return True
        
        if self.state == CircuitState.OPEN:
            if time.time() - (self.last_failure_time or 0) > self.config.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                self.half_open_calls = 0
                return True
            return False
        
        if self.state == CircuitState.HALF_OPEN:
            if self.half_open_calls < self.config.half_open_max_calls:
                self.half_open_calls += 1
                return True
            return False
        
        return True
    
    def record_success(self) -> None:
        """Record a successful operation."""
        self.failure_count = 0
        self.success_count += 1
        
        if self.state == CircuitState.HALF_OPEN:
            if self.success_count >= self.config.half_open_max_calls:
                self.state = CircuitState.CLOSED
                self.success_count = 0
    
    def record_failure(self) -> None:
        """Record a failed operation."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.OPEN
        elif self.failure_count >= self.config.failure_threshold:
            self.state = CircuitState.OPEN
    
    def get_state(self) -> CircuitState:
        """Get current circuit state."""
        return self.state


class RetryController:
    """
    Manages retry logic for operations with configurable policies.
    
    Features:
    - Exponential backoff with jitter
    - Circuit breaker pattern
    - Configurable retry policies
    - Statistics tracking
    """
    
    def __init__(self):
        self._stats = RetryStats()
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}
        self._default_config = RetryConfig()
    
    def execute_with_retry(
        self,
        operation: Callable[..., Any],
        *args,
        config: Optional[RetryConfig] = None,
        circuit_name: Optional[str] = None,
        **kwargs
    ) -> Any:
        """
        Execute an operation with retry logic.
        
        Args:
            operation: The operation to execute
            *args: Positional arguments for operation
            config: Retry configuration
            circuit_name: Optional circuit breaker name
            **kwargs: Keyword arguments for operation
            
        Returns:
            Operation result
            
        Raises:
            Exception: If all retries exhausted
        """
        config = config or self._default_config
        
        # Check circuit breaker
        if circuit_name:
            circuit = self._get_circuit_breaker(circuit_name)
            if not circuit.can_execute():
                raise Exception(f"Circuit breaker '{circuit_name}' is open")
        
        last_exception: Optional[Exception] = None
        
        for attempt in range(1, config.max_attempts + 1):
            try:
                result = operation(*args, **kwargs)
                self._stats.record_attempt(True)
                
                if circuit_name:
                    circuit.record_success()
                
                return result
                
            except config.retryable_exceptions as e:
                last_exception = e
                self._stats.record_attempt(False)
                
                if circuit_name:
                    circuit.record_failure()
                
                if attempt < config.max_attempts:
                    self._stats.record_retry()
                    
                    if config.on_retry_callback:
                        config.on_retry_callback(attempt, e)
                    
                    delay = self._calculate_delay(attempt, config)
                    time.sleep(delay)
                else:
                    if config.on_exhausted_callback:
                        config.on_exhausted_callback(e)
        
        raise last_exception or Exception("All retry attempts exhausted")
    
    def _calculate_delay(self, attempt: int, config: RetryConfig) -> float:
        """Calculate delay before next retry attempt."""
        if config.policy == RetryPolicy.FIXED:
            delay = config.base_delay
        elif config.policy == RetryPolicy.LINEAR:
            delay = config.base_delay * attempt
        else:  # EXPONENTIAL
            delay = config.base_delay * (2 ** (attempt - 1))
        
        # Add jitter (±25%)
        jitter = delay * 0.25
        delay = delay + random.uniform(-jitter, jitter)
        
        return min(delay, config.max_delay)
    
    def _get_circuit_breaker(self, name: str) -> CircuitBreaker:
        """Get or create a circuit breaker."""
        if name not in self._circuit_breakers:
            self._circuit_breakers[name] = CircuitBreaker(
                name, CircuitBreakerConfig()
            )
        return self._circuit_breakers[name]
    
    def get_circuit_state(self, name: str) -> Optional[CircuitState]:
        """Get circuit breaker state."""
        circuit = self._circuit_breakers.get(name)
        return circuit.get_state() if circuit else None
    
    def reset_circuit(self, name: str) -> bool:
        """Reset a circuit breaker to closed state."""
        circuit = self._circuit_breakers.get(name)
        if circuit:
            circuit.state = CircuitState.CLOSED
            circuit.failure_count = 0
            circuit.success_count = 0
            return True
        return False
    
    def get_stats(self) -> RetryStats:
        """Get retry statistics."""
        return self._stats
    
    def reset_stats(self) -> None:
        """Reset statistics."""
        self._stats = RetryStats()


def with_retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    policy: RetryPolicy = RetryPolicy.EXPONENTIAL,
    retryable_exceptions: Tuple[Type[Exception], ...] = (Exception,),
):
    """Decorator for adding retry logic to functions."""
    def decorator(func: Callable) -> Callable:
        controller = RetryController()
        config = RetryConfig(
            max_attempts=max_attempts,
            base_delay=base_delay,
            max_delay=max_delay,
            policy=policy,
            retryable_exceptions=retryable_exceptions,
        )
        
        @wraps(func)
        def wrapper(*args, **kwargs):
            return controller.execute_with_retry(func, *args, config=config, **kwargs)
        
        return wrapper
    return decorator
