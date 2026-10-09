import requests

import config


def send(msg: str):
    """Telegram message. Token/chat id na ho to chupchap skip."""
    if not config.TG_TOKEN or not config.TG_CHAT:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{config.TG_TOKEN}/sendMessage",
            data={"chat_id": config.TG_CHAT, "text": msg[:3500]},
            timeout=10,
        )
    except Exception:
        pass  # token kabhi log me nahi jaana chahiye, isliye error print nahi karte
