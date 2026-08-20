from pydantic_settings import BaseSettings
from pydantic import AliasChoices, Field, ConfigDict


class Settings(BaseSettings):
    model_config = ConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    db_url: str = Field(default="postgresql+asyncpg://sentiment:sentiment@localhost:5432/stocksentiment")
    db_url_sync: str = Field(default="postgresql://sentiment:sentiment@localhost:5432/stocksentiment")

    finnhub_key: str = Field(default="")

    reddit_client_id: str = Field(default="")
    reddit_client_secret: str = Field(default="")
    reddit_user_agent: str = Field(default="StockSentimentBot/1.0")

    fred_api_key: str = Field(default="")
    fmp_api_key: str = Field(default="")

    llm_provider: str = Field(default="auto")
    open_ai_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("OPENAI_API_KEY", "OPEN_AI_API_KEY"),
    )
    open_ai_endpoint: str = Field(
        default="https://api.openai.com/v1",
        validation_alias=AliasChoices("OPENAI_ENDPOINT", "OPEN_AI_ENDPOINT"),
    )
    open_ai_default_model: str = Field(
        default="gpt-4o-mini",
        validation_alias=AliasChoices("OPENAI_DEFAULT_MODEL", "OPEN_AI_DEFAULT_MODEL"),
    )
    open_ai_escalation_model: str = Field(
        default="gpt-4o",
        validation_alias=AliasChoices("OPENAI_ESCALATION_MODEL", "OPEN_AI_ESCALATION_MODEL"),
    )

    anthropic_api_key: str = Field(default="")
    anthropic_api_base: str = Field(default="https://api.anthropic.com")
    anthropic_api_version: str = Field(default="2023-06-01")
    anthropic_default_model: str = Field(default="claude-3-5-haiku-latest")
    anthropic_escalation_model: str = Field(default="claude-3-7-sonnet-latest")

    # Agent cache TTL in seconds (6 hours)
    agent_cache_ttl: int = 21600

    # Macro overlay weight (15% macro, 85% company-specific)
    macro_weight: float = 0.15

    # Local filesystem location for analysis exports
    analysis_output_dir: str = Field(default="output/analysis")

    # Optional SMTP settings for emailing generated summaries
    smtp_host: str = Field(default="")
    smtp_port: int = Field(default=587)
    smtp_username: str = Field(default="")
    smtp_password: str = Field(default="")
    smtp_use_tls: bool = Field(default=True)
    smtp_from: str = Field(default="")
    email_to: str = Field(default="")


settings = Settings()
