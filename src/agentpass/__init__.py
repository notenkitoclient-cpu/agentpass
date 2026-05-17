"""
AgentPass — M2M Wallet & Passport Infrastructure for AI Agents

内部パッケージ構造を意識せずにインポート可能:

    from agentpass import AuthorizationMiddleware, AgentPassCrawler
    from agentpass import issue_token, TokenRequest, verify_token
    from agentpass import CircuitBreaker, AnomalyDetector, CreditScorer
"""

from __future__ import annotations

from core.agentpass_crawler import AgentPassCrawler, MerchantMetadata, PricingSchema
from core.anomaly_detector import AnomalyDetector
from core.authorization_middleware import AuthorizationMiddleware
from core.circuit_breaker import (
    BudgetExceededError,
    CircuitBreaker,
    CircuitBreakerError,
    RateLimitedError,
)
from core.token_issuer import IssuedToken, TokenRequest, generate_keypair, issue_token
from core.token_verifier import (
    DestinationMismatchError,
    InvalidPayloadError,
    TokenExpiredError,
    VerificationError,
    VerifiedClaims,
    verify_token,
)
from identity.agent_signer import derive_agent_id
from identity.credit_scorer import CreditScorer

__version__ = "1.0.0-beta1"

__all__ = [
    # ミドルウェア
    "AuthorizationMiddleware",
    # トークン発行
    "TokenRequest",
    "IssuedToken",
    "issue_token",
    "generate_keypair",
    # トークン検証
    "verify_token",
    "VerifiedClaims",
    "VerificationError",
    "InvalidPayloadError",
    "TokenExpiredError",
    "DestinationMismatchError",
    # サーキットブレーカー
    "CircuitBreaker",
    "CircuitBreakerError",
    "BudgetExceededError",
    "RateLimitedError",
    # クローラー
    "AgentPassCrawler",
    "MerchantMetadata",
    "PricingSchema",
    # アノマリー検知
    "AnomalyDetector",
    # アイデンティティ
    "CreditScorer",
    "derive_agent_id",
    # バージョン
    "__version__",
]
