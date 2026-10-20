"""Fact-check pass for pages where accuracy is the product (e.g. History Decoded).

Two independent references are used for every check:
  1. Wikipedia: the most relevant article intros are fetched live and handed to the checker as
     reference text (encyclopedia figures, not the model's memory).
  2. Google Search grounding: Gemini checks each date, number and name against the live web.
The checker returns pass / fix / fail. "fix" comes with corrected text that uses the most widely
cited figures; "fail" means the core claim is wrong and the post must not go out.

Switch on per page with "fact_check": true in the page's image block.
"""
import json
import re

from common import log

UA = {"User-Agent": "HistoryDecodedFactCheck/1.0 (educational Facebook page; contact via page)"}

CHECK_PROMPT = """You are a strict fact-checker for the Facebook Page "{brand}". Accuracy matters more than drama.

TEXT TO CHECK:
---
{text}
---

REFERENCE (live Wikipedia article intros):
---
{reference}
---

Check EVERY date, year, number, duration, name, place and cause-and-effect claim in the text against the
reference and against Google Search results from reliable sources (encyclopedias such as Wikipedia and
Britannica, museums, universities, government or scientific bodies).
Rules:
- Where sources disagree, use the figure most widely cited by encyclopedias and say "around"/"about".
- Comparisons ("X years before Y", "still alive when...") must follow from the verified dates.
- Ancient dates are estimates: false precision is an error.
- Quotes attributed to real people must be verifiable word for word, otherwise they are errors.
- verdict "pass": everything checks out. "fix": the main idea is true but some details are wrong or overstated.
  "fail": the main claim itself is false or cannot be verified.

Return ONLY a JSON object (no markdown) with keys:
"verdict": "pass" | "fix" | "fail",
"issues": list of short strings (what was wrong and the correct value), empty if pass,
"verified_facts": one short paragraph stating the verified facts with their years (hedged where needed),
"corrected": {fields} (same style and length limits as the original; only when verdict is "fix", else {{}}),
"sources": up to 3 URLs you relied on"""


def _wiki(query, n=2, chars=1800):
    """Intros of the top Wikipedia matches for the query. Returns (text, [urls])."""
    import requests
    try:
        r = requests.get("https://en.wikipedia.org/w/api.php", headers=UA, timeout=20, params={
            "action": "query", "list": "search", "srsearch": query[:250], "srlimit": n, "format": "json"})
        titles = [h["title"] for h in r.json().get("query", {}).get("search", [])]
        if not titles:
            return "", []
        r = requests.get("https://en.wikipedia.org/w/api.php", headers=UA, timeout=20, params={
            "action": "query", "prop": "extracts", "exintro": 1, "explaintext": 1, "redirects": 1,
            "titles": "|".join(titles), "format": "json"})
        pages = r.json().get("query", {}).get("pages", {}).values()
        text = "\n\n".join(f"[{p.get('title')}]\n{str(p.get('extract', ''))[:chars]}" for p in pages)
        urls = ["https://en.wikipedia.org/wiki/" + t.replace(" ", "_") for t in titles]
        return text, urls
    except Exception as exc:
        log(f"wikipedia lookup failed: {str(exc)[:120]}")
        return "", []


def _parse(text):
    text = (text or "").strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def check(page, text, queries, fields_hint="{}"):
    """Returns dict(verdict, issues, verified_facts, corrected, sources). Raises if no check was possible."""
    import transform
    from google.genai import types
    ref_parts, urls = [], []
    for q in [q for q in queries if q][:2]:
        t, u = _wiki(q)
        if t:
            ref_parts.append(t)
            urls += u
    reference = "\n\n".join(ref_parts) or "(no Wikipedia match found - rely on Google Search)"
    prompt = CHECK_PROMPT.format(brand=page["brand"], text=text[:4000], reference=reference[:7000],
                                 fields=fields_hint)
    client = transform._gemini_client()
    data, grounded = {}, False
    try:
        resp, _ = transform.generate(client, prompt, types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())], temperature=0))
        data, grounded = _parse(resp.text), True
    except Exception as exc:
        log(f"[{page['key']}] search-grounded check unavailable ({str(exc)[:120]}), using Wikipedia only")
    if not data.get("verdict"):
        if not ref_parts:
            raise RuntimeError("fact-check impossible: no search grounding and no Wikipedia reference")
        resp, _ = transform.generate(client, prompt, types.GenerateContentConfig(temperature=0))
        data, grounded = _parse(resp.text), False
    verdict = str(data.get("verdict", "")).lower()
    if verdict not in ("pass", "fix", "fail"):
        raise RuntimeError("fact-check returned no verdict")
    src = [s for s in (data.get("sources") or []) if isinstance(s, str) and s.startswith("http")]
    data["verdict"] = verdict
    data["sources"] = list(dict.fromkeys(src + urls))[:4]
    data["grounded"] = grounded
    log(f"[{page['key']}] fact-check {verdict}{' (search+wiki)' if grounded else ' (wiki only)'}: "
        + "; ".join(str(i) for i in (data.get("issues") or []))[:400])
    return data


def check_card(page, card):
    """Verifies a card in place. Returns a short log note. Raises when the card must not be posted."""
    text = "\n".join([str(card.get("headline", "")), str(card.get("body", ""))]
                     + [str(b) for b in card.get("bullets") or []] + [str(card.get("caption", ""))])
    hint = '{"headline": "...", "body": "...", "bullets": [...], "caption": "..."}'
    res = check(page, text, [str(card.get("topic", "")), str(card.get("headline", ""))], hint)
    if res["verdict"] == "fail":
        raise RuntimeError("fact-check FAILED: " + "; ".join(map(str, res.get("issues") or []))[:300])
    if res["verdict"] == "fix":
        fix = res.get("corrected") or {}
        for k in ("headline", "body", "caption"):
            if str(fix.get(k) or "").strip():
                card[k] = str(fix[k]).strip()
        if isinstance(fix.get("bullets"), list) and fix["bullets"]:
            card["bullets"] = [str(b) for b in fix["bullets"]][:5]
    if str(res.get("verified_facts") or "").strip():
        card["_facts"] = str(res["verified_facts"]).strip()
    card["_sources"] = res["sources"]
    return f"factcheck {res['verdict']} " + " ".join(res["sources"][:2])


def check_script(page, script, card):
    """True if the explainer voice-over passes; otherwise returns the list of issues."""
    text = " ".join(str(s.get("vo", "")) for s in script.get("scenes", [])) + "\n" + str(script.get("caption", ""))
    res = check(page, text, [str(card.get("topic", "")), str(card.get("headline", ""))])
    return True if res["verdict"] == "pass" else (res.get("issues") or ["details could not be verified"])
