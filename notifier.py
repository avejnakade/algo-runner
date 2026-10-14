import requests

import config


def send(msg: str):
    """Telegram message. Fail ho to wajah (token ke bina) log me print hoti hai."""
    if not config.TG_TOKEN or not config.TG_CHAT:
        print("telegram: TOKEN ya CHAT_ID set nahi hai (GitHub Secrets ke naam check karo)")
        return
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{config.TG_TOKEN}/sendMessage",
            data={"chat_id": config.TG_CHAT, "text": msg[:3500]},
            timeout=10,
        )
        if r.status_code != 200:
            try:
                desc = r.json().get("description", "")
            except Exception:
                desc = ""
            print(f"telegram: http {r.status_code} {desc[:120]}")
    except Exception as e:
        print(f"telegram: {type(e).__name__}")
