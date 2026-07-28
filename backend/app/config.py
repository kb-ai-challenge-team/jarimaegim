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
    #: 서브에이전트 11개가 쓰는 모델. 하는 일이 "열거된 선택지 중에서 고르기"라 작은 모델로
    #: 충분하고, 케이스당 호출 수가 많은 쪽이라 비용도 여기서 정해진다. 비우면 대화 모델을 쓴다.
    ai_agent_model: str = ""
    #: 메인 에이전트가 쓰는 모델. 팀 보고 전체를 읽고 설명문을 쓰는 유일한 자리라 추론 여력이
    #: 필요하다. 실행당 한 번만 부른다. 비우면 대화 모델을 쓴다.
    ai_main_model: str = ""
    ai_explanation_enabled: bool = True
    ai_daily_request_limit: int = 20
    ipzitalk_mcp_enabled: bool = False
    ipzitalk_mcp_command: str = ""
    ipzitalk_mcp_args: str = ""
    naver_maps_client_id: str = ""
    naver_maps_client_secret: str = ""

    embedding_model: str = ""
    embedding_dimension: int = 1536

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

    @property
    def agent_model(self) -> str:
        return self.ai_agent_model or self.ai_chat_model

    @property
    def main_agent_model(self) -> str:
        return self.ai_main_model or self.ai_chat_model

    @property
    def retrieval_configured(self) -> bool:
        """검색은 벡터 저장소와 질의 임베딩이 모두 있어야 성립한다."""
        return bool(self.supabase_configured and self.openai_api_key and self.embedding_model)


@lru_cache

def get_settings() -> Settings:
    return Settings()
