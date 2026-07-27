from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env", ".env.local"), extra="ignore")

    app_env: str = "development"
    app_origin: str = "http://127.0.0.1:4173"
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    next_public_kakao_map_js_key: str = ""
    anon_token_pepper: str = "development-only-change-before-deploy"
    anonymous_session_hours: int = 24
    document_storage_dir: str = ".data/documents"
    policy_params_path: str = "config/policy-params.json"

    kakao_rest_api_key: str = ""
    openai_api_key: str = ""
    ai_chat_model: str = ""
    ai_explanation_enabled: bool = True
    ai_daily_request_limit: int = 20
    ipzitalk_mcp_enabled: bool = False
    ipzitalk_mcp_command: str = ""
    ipzitalk_mcp_args: str = ""
    naver_maps_client_id: str = ""
    naver_maps_client_secret: str = ""

    seoul_open_data_key: str = ""
    data_go_kr_service_key: str = ""
    bizinfo_api_key: str = ""
    kstartup_api_key: str = ""
    finlife_api_key: str = ""
    seoul_commercial_api_url: str = ""
    bizinfo_api_url: str = ""
    kstartup_api_url: str = ""
    finlife_api_url: str = ""
    finlife_api_base_url: str = ""

    privacy_rights_email: str = ""
    financial_application_enabled: bool = False
    consultation_transfer_enabled: bool = False
    mydata_enabled: bool = False

    @property
    def supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_role_key)

    @property
    def ipzitalk_configured(self) -> bool:
        """Every upstream key presale-mcp needs. A partial set would fail at call time, not startup."""
        return bool(self.ipzitalk_mcp_enabled and self.ipzitalk_mcp_command and self.kakao_rest_api_key
                    and self.data_go_kr_service_key and self.naver_maps_client_id and self.naver_maps_client_secret)


@lru_cache

def get_settings() -> Settings:
    return Settings()
