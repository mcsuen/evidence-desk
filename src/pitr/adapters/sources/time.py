MARKET_ZONES = {'SSE': 'Asia/Shanghai', 'SZSE': 'Asia/Shanghai', 'BSE': 'Asia/Shanghai', 'HKEX': 'Asia/Hong_Kong',
                'NASDAQ': 'America/New_York', 'NYSE': 'America/New_York', 'AMEX': 'America/New_York', 'US': 'America/New_York'}


def publication_timestamp(item):
    """Directories often give a date only; treat it as end of that day in the market's zone."""
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    value = item.published_at
    if not value: return None
    if len(value) == 10:
        zone = ZoneInfo(MARKET_ZONES.get(item.market, 'UTC'))
        return datetime.fromisoformat(value).replace(hour=23, minute=59, second=59, tzinfo=zone).astimezone(timezone.utc).isoformat()
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None: parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()
