# Project memory: reels-autoposter

Durable, approved knowledge about this system. Read this first in every new session; add to the
Decision log whenever something is decided. Keep it short and factual.

## What it is
Automated faceless Reels for the owner's Facebook Pages, run by GitHub Actions with a Google Sheet
("Reels Queue") as the queue and log, and Google Drive for renders and published copies
("Reels Autoposter - Published", one .mp4 + .json sidecar per post).

## Pages (config.json)
| Key | Page | Language / audience | Notes |
|---|---|---|---|
| US | Throttle Decoded | US English, cars | 2 AI Reels/day, no bundle clips (originals only); narrator: garage buddy (Algenib) |
| UAE | Stay Decoded | English, hotels/travel | minimal: daily text post only (no Reels) |
| PH | Alaga Explained | Taglish, pets (PH) | light: 5 clip Reels + 1 AI Reel/day; best organic grower |
| PAWS | Pawside Giggles | English, pets | |
| DEM | Navigating Dementia Together | English, caregivers | 3 AI Reels/day; ~60% US viewers; narrator stays gentle |
| FIN | Pera Decoded | Taglish, money (PH/OFW) | paused: daily text post only |
| HOME | Home Hacks Decoded | US English, home tips | 2 AI Reels/day, US time zone |
| HIST | History Decoded | US English, world history | 2 AI Reels/day, case-file look, secret-teller narrator (Fenrir) |
| RET / CRED / MED / SMB | Retirement / Credit / Medical Bills / Small Business Decoded | US English, money basics | YouTube-only (youtube_only: true): Reel + sidecar saved to Published, no Facebook; fact-checked, sourced, general education only |
| BYA | Byahe ni Nanay | Filipino, family travel | owner's own finished videos (byahe.py): 45 Reels + 6 long-forms, 1 post/day 19:00 PH from Drive "Byahe ni Nanay - Queue" (queue.json order); state in sheet tab BYA; byahe.live=false until owner approves |
| KAS | Chika ng Kasaysayan | Taglish, PH history | PARKED (2026-11-04, do not launch); narrator Tita Chari (Laomedeia, female) |

## How a Reel is made (explainer.py)
1. Gemini writes the script: 3 hook options -> judge picks one; word budget (image.max_words, default 70; lists +25).
2. Fact-check on pages with image.fact_check.
3. Clips: Pixabay/Pexels search + Gemini thumbnail check; Wikimedia Commons public-domain images (image.commons),
   file name must contain the person/place; image.place_guard rejects clips tagged with another place.
   No fitting clip -> post photo still -> reuse another moment of an on-topic clip -> page's generic clip (last resort).
4. Voice: Gemini TTS (page voice + voice_style); Kokoro only where kokoro_voice is set.
5. Captions and scene cuts follow the real speech (faster-whisper word timing, falls back to an estimate).
6. Remotion renders overlays; hook text is visible from frame 0.
7. Gemini video QA watches the result; "block" -> safer photo Reel instead.

## Standing rules
- Free or practical first; paid tools/boosts only with the owner's approval and the exact cost shown.
- No boosting for now (Nov 2026); grow with hooks, retention, more posts, follower invites.
- US content and US audience first (2026-11-04): Gemini spend goes to US pages; PH pages stay minimal.
- Taglish voice-overs: words in config "pronounce" are respelled for the voice only; words in "never_heard" are checked by Whisper and the Reel is not posted if said wrong (e.g. manunulat, never "manunulot").
- Never invent facts, quotes, dates or citations; label legends ("ayon sa kuwento").
- Historical pages: no living politicians or modern party politics.
- Never handle passwords, tokens or keys; the owner adds secrets in GitHub himself.
- Nothing public or irreversible without the owner's go-ahead; previews (images.yml, mode=preview) are safe.
- Owner reads on his phone: short updates, normal hyphens only, full URLs in every instruction.
- Owner's name and email never appear on anything followers see.

## Decision log
- 2026-11-01: About 6 in 10 Reels were falling back to static cards (one scene without a clip killed the Reel). Fixed with scene-level fallbacks; scripts shortened (Reels ran 45-70 s, viewers left at 2-7 s).
- 2026-11-01: Hook rules: hook on the first spoken word, same idea on screen and spoken, open loop + mid re-hook, loop ending, moving scene-1 shot.
- 2026-11-01: Sheets 429 errors -> gspread client retries on 429.
- 2026-11-02: Narrator personas (image.narrator) for KAS, HIST, US. Tita Chari must be a woman: Laomedeia.
- 2026-11-02: Captions synced to real speech with faster-whisper.
- 2026-11-03: Pronunciation guard (transform.speak): respelling + Whisper check, fails closed.
- 2026-11-04: NEW DIRECTION (owner): US content and US audience first; stop spending on low-ROI niches. Pera Decoded paused or minimal; KAS parked (not launched); Alaga Explained light posting only, no extra Gemini spend. Budget goes to History Decoded (2/day, secret-teller style), Navigating Dementia Together (US caregivers; Reels also to its YouTube via shorts-crossposter once the owner adds the token), Home Hacks Decoded and Throttle Decoded (originals only). New US money series for the YouTube channels Retirement Decoded, Credit Decoded, Medical Bills Decoded, Small Business Decoded: original, fact-checked, sourced, no financial-advice framing, no clickbait, own sidecar brand per channel in the Published folder. Per-page numbers and cost change need the owner's approval in chat before anything is switched on.
- 2026-11-04: Approved numbers (owner): AI Reels/day US 2, HIST 2, DEM 3, HOME 2, PH 1 (+5 clip Reels), UAE 0, FIN 0, KAS 0; text posts stay. Spend cap stays US$50/month (option B). HIST case-file + secret-teller style is now the live default. Money series YouTube-only, 1/day each after preview approval (slots stay empty until then).
- 2026-11-05: Money series (RET, CRED, MED, SMB) use the "board" look (animated explainer cards, no stock footage; stock clips failed QA for money topics). Owner approved going live: 1 Reel/day each at 10:00, 13:00, 15:00, 18:00 US Eastern, saved to the Published folder for shorts-crossposter.
- 2026-11-06: Gemini Interactions API began answering 404 "Model not found" for both TTS models (about 16:47 UTC); all Reels failed or fell back to photos. transform._speak_take now skips dead routes and falls back to the classic generateContent API (v1beta) and config tts_extra_models. On that route the style note is NOT sent (it gets read aloud), so narrator tone is plainer until the Interactions route returns.
- 2026-11-09: Byahe ni Nanay Page created (Graph Page ID in secret FB_PAGE_ID_BYA). byahe.py posts the owner's ready-made videos, no AI generation; long-forms via chunked /videos upload. Manual check: Actions > Byahe ni Nanay > check.
- Next: animated text scenes instead of stock footage when nothing fits; one fixed look per page; narrators for the other pages.
