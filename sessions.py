import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass, field

from config import (
    HYPERFLO_SESSION_SECRET,
    SESSION_IDLE_TIMEOUT,
    SESSION_MAX_AGE,
    SESSION_MAX_COUNT,
)

# Sessions stockees cote serveur, en memoire.
# - Le cookie ne contient qu'un jeton aleatoire; le serveur ne garde que son
#   HMAC, donc une fuite de la liste des sessions ne donne aucun jeton utilisable.
# - Une session peut etre revoquee immediatement (logout, page admin).
# - Un redemarrage du service deconnecte tout le monde. Cela impose un seul
#   worker Uvicorn (c'est deja le cas).

SESSION_COOKIE = "__Host-hyperflo_session"
CSRF_COOKIE = "__Host-hyperflo_csrf"


@dataclass
class Session:
    public_id: str
    username: str
    csrf_token: str
    ip: str
    user_agent: str
    created: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)

    def to_public(self, current: bool = False) -> dict:
        return {
            "id": self.public_id,
            "username": self.username,
            "ip": self.ip,
            "user_agent": self.user_agent,
            "created": int(self.created),
            "last_seen": int(self.last_seen),
            "expires": int(self.expires_at()),
            "current": current,
        }

    def expires_at(self) -> float:
        return min(self.created + SESSION_MAX_AGE, self.last_seen + SESSION_IDLE_TIMEOUT)


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(token: str) -> str:
        return hmac.new(
            HYPERFLO_SESSION_SECRET.encode(),
            token.encode(),
            hashlib.sha256,
        ).hexdigest()

    def _purge(self, now: float) -> None:
        expired = [
            key for key, session in self._sessions.items()
            if session.expires_at() <= now
        ]
        for key in expired:
            del self._sessions[key]

    def create(self, username: str, ip: str, user_agent: str) -> tuple[str, Session]:
        token = secrets.token_urlsafe(32)
        session = Session(
            public_id=secrets.token_hex(8),
            username=username,
            csrf_token=secrets.token_urlsafe(32),
            ip=ip,
            user_agent=user_agent[:200],
        )

        with self._lock:
            self._purge(time.time())
            # Limite le nombre de sessions: on retire les plus anciennes.
            while len(self._sessions) >= SESSION_MAX_COUNT:
                oldest = min(self._sessions, key=lambda k: self._sessions[k].last_seen)
                del self._sessions[oldest]
            self._sessions[self._key(token)] = session

        return token, session

    def get(self, token: str | None, touch: bool = True) -> Session | None:
        if not token or len(token) > 128:
            return None

        key = self._key(token)
        now = time.time()

        with self._lock:
            session = self._sessions.get(key)
            if session is None:
                return None
            if session.expires_at() <= now:
                del self._sessions[key]
                return None
            if touch:
                session.last_seen = now
            return session

    def revoke_token(self, token: str | None) -> Session | None:
        if not token:
            return None
        with self._lock:
            return self._sessions.pop(self._key(token), None)

    def revoke_public_id(self, public_id: str) -> Session | None:
        with self._lock:
            for key, session in list(self._sessions.items()):
                if hmac.compare_digest(session.public_id, public_id):
                    return self._sessions.pop(key)
        return None

    def revoke_all_except(self, keep: Session | None) -> int:
        with self._lock:
            keys = [
                key for key, session in self._sessions.items()
                if session is not keep
            ]
            for key in keys:
                del self._sessions[key]
            return len(keys)

    def list(self) -> list[Session]:
        with self._lock:
            self._purge(time.time())
            return sorted(self._sessions.values(), key=lambda s: s.created)


sessions = SessionStore()
