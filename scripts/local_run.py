"""Windows-only local launcher used by run-local.cmd."""
import getpass
import json
import os
import secrets
import sys
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def local_settings():
    # An override lets a local smoke check use throwaway data without touching real votes.
    data_dir = Path(os.environ.get("RATE_FRIENDS_LOCAL_DATA_DIR", "data")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    config_path = data_dir / "local-config.json"
    if config_path.exists():
        config = json.loads(config_path.read_text(encoding="utf-8"))
    else:
        print("Ilk kurulum: yonetici parolasi bu terminalde gorunmez.")
        password = getpass.getpass("Yonetici parolasi (en az 16 karakter): ")
        confirm = getpass.getpass("Parolayi tekrar girin: ")
        if len(password) < 16 or password != confirm:
            raise SystemExit("Parola kisa veya iki giris ayni degil. Ayar kaydedilmedi.")
        config = {
            "admin_password": password,
            "session_secret": secrets.token_urlsafe(48),
        }
        with config_path.open("x", encoding="utf-8") as file:
            json.dump(config, file)
        print("Yerel ayarlar kaydedildi.")
    if len(config.get("admin_password", "")) < 16 or len(config.get("session_secret", "")) < 32:
        raise SystemExit("Yerel ayarlar gecersiz: " + str(config_path))
    os.environ["ADMIN_PASSWORD"] = config["admin_password"]
    os.environ["SESSION_SECRET"] = config["session_secret"]
    os.environ["DATA_DIR"] = str(data_dir)
    os.environ["COOKIE_SECURE"] = "0"
    return config_path


if __name__ == "__main__":
    if sys.platform != "win32":
        raise SystemExit("Bu calistirici yalnizca Windows icindir.")
    local_settings()
    print("Uygulama: http://127.0.0.1:8000/")
    print("Yonetici girisi: http://127.0.0.1:8000/admin/login")
    print("Durdurmak icin Ctrl+C basin.")
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, workers=1, access_log=False)
