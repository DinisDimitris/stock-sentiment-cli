from pydantic_settings import BaseSettings
from pydantic import Field, ConfigDict


class Settings(BaseSettings):
    model_config = ConfigDict(env_file=".env", env_file_encoding="utf-8")
    db_url: str = Field(default="postgresql+asyncpg://sentiment:sentiment@localhost:5432/stocksentiment")
    db_url_sync: str = Field(default="postgresql://sentiment:sentiment@localhost:5432/stocksentiment")

    github_pat: str = Field(default="")
    finnhub_key: str = Field(default="")

    reddit_client_id: str = Field(default="")
    reddit_client_secret: str = Field(default="")
    reddit_user_agent: str = Field(default="StockSentimentBot/1.0")

    fred_api_key: str = Field(default="")
    fmp_api_key: str = Field(default="")
    
    open_ai_api_key: str = Field(default="")
    open_ai_endpoint: str = "https://models.inference.ai.azure.com"
    github_models_default: str = Field(default="")
    github_models_escalation: str = Field(default="")

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
