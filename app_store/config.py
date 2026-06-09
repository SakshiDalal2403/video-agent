import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    @property
    def redis_url(self) -> str | None:
        return os.getenv("REDIS_URL")

    @property
    def session_ttl_seconds(self) -> int:
        try:
            return int(os.getenv("SESSION_TTL_SECONDS", "7200"))
        except ValueError:
            return 7200

    @property
    def cleanup_cooldown_seconds(self) -> int:
        try:
            return int(os.getenv("CLEANUP_COOLDOWN_SECONDS", "3600"))
        except ValueError:
            return 3600

settings = Settings()
