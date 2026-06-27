#!/usr/bin/env python3
"""
HOA Library — Daily news fetcher
Pulls RSS feeds from Horn of Africa sources, deduplicates, updates data.json
"""

import json
import hashlib
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
import os
import time
import re

DATA_PATH = "library/data.json"

# RSS sources — news only (daily fetch)
NEWS_FEEDS = [
    # ── SOMALIA DEDICATED ─────────────────────────────────────────────────
    {"source": "Garowe Online",        "region": "Somalia",  "url": "https://www.garoweonline.com/en/rss",               "filter": []},
    {"source": "Hiiraan Online",       "region": "Somalia",  "url": "https://www.hiiraan.com/rss/hiiraan_news.xml",      "filter": []},
    {"source": "Goobjoog News",        "region": "Somalia",  "url": "https://goobjoog.com/english/feed/",                "filter": []},
    {"source": "Somali Guardian",      "region": "Somalia",  "url": "https://somaliguardian.com/feed/",                  "filter": []},
    {"source": "Radio Dalsan",         "region": "Somalia",  "url": "https://www.radiodalsan.com/en/feed/",              "filter": []},

    # ── SOMALILAND ────────────────────────────────────────────────────────
    {"source": "Somaliland Sun",       "region": "Somalia",  "url": "https://somalilandsun.com/feed/",                   "filter": []},
    {"source": "Somaliland Standard",  "region": "Somalia",  "url": "https://somalilandstandard.com/feed/",              "filter": []},

    # ── ETHIOPIA ──────────────────────────────────────────────────────────
    {"source": "Addis Standard",       "region": "Ethiopia", "url": "https://addisstandard.com/feed/",                   "filter": []},
    {"source": "Ethiopia Insight",     "region": "Ethiopia", "url": "https://ethiopia-insight.com/feed/",                "filter": []},
    {"source": "The Reporter Ethiopia","region": "Ethiopia", "url": "https://www.thereporterethiopia.com/feed/",         "filter": []},

    # ── REGIONAL / MULTI-COUNTRY ──────────────────────────────────────────
    {"source": "The East African",     "region": "Somalia",  "url": "https://www.theeastafrican.co.ke/rss",             "filter": ["somalia","ethiopia","eritrea","djibouti","horn","al-shabaab","somaliland"]},
    {"source": "Africa Report",        "region": "Somalia",  "url": "https://www.theafricareport.com/feed/",            "filter": ["somalia","ethiopia","eritrea","djibouti","horn","somaliland","tigray"]},
    {"source": "African Arguments",    "region": "Somalia",  "url": "https://africanarguments.org/feed/",               "filter": ["somalia","ethiopia","eritrea","djibouti","horn","somaliland","tigray","houthi","kenya"]},
    {"source": "Crisis Group",         "region": "Somalia",  "url": "https://www.crisisgroup.org/rss.xml",              "filter": ["somalia","ethiopia","eritrea","djibouti","horn","somaliland","kenya","sudan"]},
    {"source": "ACLED",                "region": "Somalia",  "url": "https://acleddata.com/feed/",                      "filter": ["somalia","ethiopia","eritrea","kenya","horn"]},

    # ── RED SEA / MARITIME ────────────────────────────────────────────────
    {"source": "Al Jazeera Horn",      "region": "Somalia",  "url": "https://www.aljazeera.com/xml/rss/all.xml",        "filter": ["somalia","ethiopia","eritrea","djibouti","horn of africa","al-shabaab","somaliland","tigray","houthi","red sea","bab al-mandeb"]},
    {"source": "Middle East Eye",      "region": "Red Sea",  "url": "https://www.middleeasteye.net/rss",                "filter": ["somalia","horn of africa","houthi","red sea","djibouti","eritrea","bab al-mandeb"]},

    # ── KENYA (border/security angle) ────────────────────────────────────
    {"source": "The Star Kenya",       "region": "Kenya",    "url": "https://www.the-star.co.ke/rss",                   "filter": ["somalia","al-shabaab","mandera","wajir","garissa","horn"]},
]

# Tag inference map
TAG_MAP = {
    "al-shabaab": "Al-Shabaab", "shabaab": "Al-Shabaab",
    "atmis": "ATMIS", "amisom": "AMISOM",
    "somaliland": "Somaliland", "berbera": "Berbera",
    "tigray": "Tigray", "tplf": "TPLF",
    "houthi": "Houthis", "red sea": "Red Sea", "bab el-mandeb": "Bab el-Mandeb",
    "ethiopia": "Ethiopia", "eritrea": "Eritrea", "kenya": "Kenya",
    "djibouti": "Djibouti", "somalia": "Somalia",
    "sna": "SNA", "danab": "Danab",
    "famine": "Food Security", "drought": "Drought",
    "au": "African Union",
    "israel": "Israel", "diplomacy": "Diplomacy",
    "military": "Military", "security": "Security",
    "election": "Elections", "governance": "Governance",
    "piracy": "Piracy", "maritime": "Maritime",
    "airstrike": "Airstrikes", "bombing": "Airstrikes",
    "puntland": "Puntland", "jubaland": "Jubaland",
    "mogadishu": "Mogadishu", "kismayo": "Kismayo",
    "wardheer": "Wardheer", "galmudug": "Galmudug",
    "clan": "Clan Conflict", "militia": "Militia",
    "idp": "Displacement", "displaced": "Displacement",
    "food security": "Food Security", "famine": "Food Security",
    "port": "Maritime", "shipping": "Maritime",
}

def infer_tags(text):
    text_lower = text.lower()
    found = []
    for kw, tag in TAG_MAP.items():
        if kw in text_lower and tag not in found:
            found.append(tag)
    return found[:5]

def infer_region(text, default_region):
    text_lower = text.lower()
    if any(w in text_lower for w in ["somalia", "mogadishu", "al-shabaab", "somaliland", "puntland", "jubaland", "galmudug", "kismayo"]):
        return "Somalia"
    if any(w in text_lower for w in ["ethiopia", "addis", "tigray", "amhara", "oromia", "abiy"]):
        return "Ethiopia"
    if any(w in text_lower for w in ["eritrea", "asmara"]):
        return "Eritrea"
    if any(w in text_lower for w in ["djibouti"]):
        return "Djibouti"
    if any(w in text_lower for w in ["kenya", "nairobi", "mandera", "wajir", "garissa"]):
        return "Kenya"
    if any(w in text_lower for w in ["red sea", "bab el-mandeb", "gulf of aden", "houthi", "bab al-mandeb"]):
        return "Red Sea"
    return default_region

def make_id(url, title):
    raw = (url or title or "").strip()
    return "n_" + hashlib.md5(raw.encode()).hexdigest()[:10]

def parse_date(date_str):
    if not date_str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for fmt in ["%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S GMT",
                "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"]:
        try:
            return datetime.strptime(date_str.strip(), fmt).strftime("%Y-%m-%d")
        except:
            pass
    m = re.search(r'(\d{4}-\d{2}-\d{2})', date_str)
    return m.group(1) if m else datetime.now(timezone.utc).strftime("%Y-%m-%d")

def strip_html(text):
    return re.sub(r'<[^>]+>', '', text or '').strip()[:300]

def fetch_feed(feed_cfg):
    items = []
    try:
        req = urllib.request.Request(
            feed_cfg["url"],
            headers={"User-Agent": "HOA-Library-Bot/1.0 (+https://abdigh26.github.io/library)"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
        root = ET.fromstring(raw)
        ns = {"atom": "http://www.w3.org/2005/Atom"}

        entries = root.findall(".//item") or root.findall(".//atom:entry", ns)

        for entry in entries[:30]:
            def get(tag, atom_tag=None):
                el = entry.find(tag)
                if el is None and atom_tag:
                    el = entry.find(atom_tag, ns)
                return (el.text or "").strip() if el is not None and el.text else ""

            title   = strip_html(get("title", "atom:title"))
            url     = get("link", "atom:link") or (entry.find("atom:link", ns).get("href","") if entry.find("atom:link",ns) is not None else "")
            date    = parse_date(get("pubDate") or get("published", "atom:published") or get("updated","atom:updated"))
            excerpt = strip_html(get("description") or get("summary","atom:summary") or get("content","atom:content"))

            if not title:
                continue

            filters = feed_cfg.get("filter", [])
            if filters:
                combined = (title + " " + excerpt).lower()
                if not any(f in combined for f in filters):
                    continue

            region = infer_region(title + " " + excerpt, feed_cfg["region"])
            tags   = infer_tags(title + " " + excerpt)
            if not tags:
                tags = [region]

            items.append({
                "id":      make_id(url, title),
                "type":    "news",
                "title":   title,
                "source":  feed_cfg["source"],
                "url":     url,
                "date":    date,
                "region":  region,
                "tags":    tags,
                "excerpt": excerpt,
            })
    except Exception as e:
        print(f"  ✗ {feed_cfg['source']}: {e}")
    return items

def load_data():
    if not os.path.exists(DATA_PATH):
        return {"news": [], "articles": [], "reports": [], "books": []}
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data):
    data["last_updated"] = datetime.now(timezone.utc).isoformat()
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def main():
    print(f"HOA Library fetch — {datetime.now(timezone.utc).isoformat()}")
    data = load_data()

    existing_ids = {item["id"] for item in data.get("news", [])}
    new_items = []

    for feed in NEWS_FEEDS:
        print(f"  Fetching {feed['source']}...")
        items = fetch_feed(feed)
        print(f"    → {len(items)} items found")
        for item in items:
            if item["id"] not in existing_ids:
                new_items.append(item)
                existing_ids.add(item["id"])
        time.sleep(1)

    # Prepend new items, keep last 300 news items total
    data["news"] = (new_items + data.get("news", []))[:300]

    save_data(data)
    print(f"\n✓ Done — {len(new_items)} new items added. Total news: {len(data['news'])}")

if __name__ == "__main__":
    main()
