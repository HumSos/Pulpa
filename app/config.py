from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    app_nombre: str = "Sistema Pulpa"
    empresa_nombre: str = "Comercializadora del Norte"
    empresa_direccion: str = ""
    empresa_telefono: str = ""
    empresa_rfc: str = ""
    database_url: str = f"sqlite:///{(BASE_DIR / 'data' / 'pulpa.db').as_posix()}"


settings = Settings()