from functools import lru_cache
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='../.env', extra='ignore', hide_input_in_errors=True)
    database_url: str = 'postgresql+psycopg://issueflow:issueflow_local@127.0.0.1:5432/issueflow'
    jwt_secret: SecretStr = Field(min_length=32)
    cookie_secure: bool = False
    allowed_origins: str = 'http://localhost:3000,http://127.0.0.1:3000'
    llm_url: str = 'https://api.deepseek.com'
    llm_api_key: SecretStr = SecretStr('')
    llm_model: str = 'deepseek-flash'
    llm_enabled: bool = True
    llm_timeout_seconds: float = Field(default=60.0, gt=0, le=120)
    demo_password: SecretStr = SecretStr('123456123456zm')

    @field_validator('jwt_secret')
    @classmethod
    def reject_placeholder_secret(cls, value: SecretStr) -> SecretStr:
        secret = value.get_secret_value()
        if (not secret.strip() or len(set(secret)) < 2 or
                secret.lower().startswith(('replace-', 'changeme', 'change-me', 'your-secret'))):
            raise ValueError('JWT_SECRET must be a generated random secret, not a placeholder')
        return value

    @field_validator('llm_url')
    @classmethod
    def safe_provider(cls, value: str) -> str:
        # The browser cannot choose a model endpoint (SSRF prevention).
        if value.rstrip('/') != 'https://api.deepseek.com':
            raise ValueError('Only the approved HTTPS DeepSeek endpoint is supported')
        return value.rstrip('/')


@lru_cache
def settings() -> Settings:
    return Settings()
