import os
import re
import json
import time
import random
import asyncio
import textwrap
import requests

from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import (
    VideoFileClip, AudioFileClip, ImageClip,
    CompositeVideoClip, concatenate_videoclips
)
import edge_tts
from google import genai
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ===================== SOZLAMALAR =====================
W, H, FPS = 720, 1280, 20
VOICE = "uz-UZ-SardorNeural"
VIDEO_PART = int(os.getenv("VIDEO_PART", "1"))
EPISODE_FILE = "episode.json"
CACHE_FILE = "pixabay_cache.json"
AUDIO_FILE = "voice.mp3"
VIDEO_FILE = "video.mp4"

PIXABAY_KEY = os.environ["PIXABAY_API_KEY"]
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def log(message):
    print(message, flush=True)


# ===================== GEMINI: ASOSIY + ZAXIRA =====================
def gemini_text(prompt):
    models = ["gemini-3.5-flash-lite", "gemini-3.8-flash"]
    last_error = None

    for model in models:
        try:
            log("Gemini modeli: " + model)
            response = client.models.generate_content(
                model=model,
                contents=prompt
            )
            result = getattr(response, "text", None)

            if not result:
                raise ValueError("Gemini bo'sh javob berdi")

            return result

        except Exception as error:
            last_error = error
            log(f"{model} ishlamadi: {error}")

    raise RuntimeError("Gemini modellarida xato: " + str(last_error))


def extract_json(raw):
    raw = re.sub(
        r"^```(?:json)?\s*|\s*```$",
        "",
        raw.strip(),
        flags=re.I
    )
    match = re.search(r"\{.*\}", raw, re.S)

    if not match:
        raise ValueError("Gemini javobidan JSON topilmadi")

    return json.loads(match.group())


# ===================== HIKOYA =====================
def create_script():

    if VIDEO_PART == 1:
        prompt = """
O'zbek tilida juda qiziqarli, sirli va hayajonli, ikki qismli hikoya yoz.

Birinchi qism 140-180 so'z bo'lsin.
Boshidan tomoshabinni qiziqtirsin.
Oxirida kuchli sirli joyda to'xtasin.

Ikkinchi qism 140-180 so'z bo'lsin.
Birinchi qismning bevosita davomi bo'lsin.
Sirni ochsin va hikoyani yakunlasin.

Har bir qism uchun Pixabay'dan haqiqiy harakatli video topishga
mos 10-12 ta inglizcha qidiruv iborasi yoz.

Faqat quyidagi tuzilishdagi JSON qaytar:

{
"title":"Hikoya nomi",
"part1":"Birinchi qism",
"part2":"Ikkinchi qism",
"queries1":["abandoned house","dark forest"],
"queries2":["old door","man walking at night"]
}
"""
        story = extract_json(gemini_text(prompt))

        for key in (
            "title", "part1", "part2",
            "queries1", "queries2"
        ):
            if key not in story:
                raise ValueError(
                    "Hikoya ma'lumoti yetishmaydi: " + key
                )

        with open(EPISODE_FILE, "w", encoding="utf-8") as f:
            json.dump(
                story,
                f,
                ensure_ascii=False,
                indent=2
            )

        return (
            story["title"],
            story["part1"],
            story["queries1"]
        )

    if VIDEO_PART == 2:
        if not os.path.exists(EPISODE_FILE):
            raise FileNotFoundError(
                "episode.json topilmadi. "
                "Birinchi qismdan saqlangan fayl kerak."
            )

        with open(EPISODE_FILE, "r", encoding="utf-8") as f:
            story = json.load(f)

        return (
            story["title"],
            story["part2"],
            story["queries2"]
        )

    raise ValueError("VIDEO_PART faqat 1 yoki 2 bo'lishi kerak")


# ===================== PIXABAY KESH VA QIDIRUV =====================
def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    return {}


def save_cache(cache):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)


def search_pixabay(query, cache):
    now = time.time()
    saved = cache.get(query)

    if saved and now - saved.get("time", 0) < 86400:
        log("Pixabay keshdan olindi: " + query)
        return saved.get("hits", [])

    response = requests.get(
        "https://pixabay.com/api/videos/",
        params={
            "key": PIXABAY_KEY,
            "q": query,
            "video_type": "film",
            "per_page": 10,
            "safesearch": "true",
            "order": "popular"
        },
        timeout=30
    )

    response.raise_for_status()
    hits = response.json().get("hits", [])

    cache[query] = {
        "time": now,
        "hits": hits
    }

    save_cache(cache)
    return hits


def download_video(url, filename):
    response = requests.get(
        url,
        stream=True,
        timeout=90
    )
    response.raise_for_status()

    with open(filename, "wb") as f:
        for chunk in response.iter_content(1024 * 256):
            if chunk:
                f.write(chunk)

    if os.path.getsize(filename) < 10000:
        raise ValueError("Yuklangan video juda kichik")

    return filename


def get_real_videos(queries):
    cache = load_cache()
    selected = []
    used_ids = set()
    sources = []

    for query in queries[:12]:
        if len(selected) >= 12:
            break

        try:
            hits = search_pixabay(query, cache)
            random.shuffle(hits)

            for hit in hits:
                if hit.get("id") in used_ids:
                    continue

                videos = hit.get("videos", {})
                data = (
                    videos.get("medium")
                    or videos.get("small")
                    or videos.get("tiny")
                )

                if not data or not data.get("url"):
                    continue

                filename = f"stock_{len(selected)}.mp4"

                try:
                    download_video(data["url"], filename)
                except Exception as error:
                    log("Video yuklash xatosi: " + str(error))
                    continue

                used_ids.add(hit["id"])
                selected.append(filename)

                if hit.get("pageURL"):
                    sources.append(hit["pageURL"])

                break

        except Exception as error:
            log(
                f"Pixabay qidiruvi o'tkazib yuborildi "
                f"({query}): {error}"
            )

    save_cache(cache)

    if not selected:
        raise RuntimeError(
            "Pixabay'dan video topilmadi. API kalitini tekshiring."
        )

    log(f"Topilgan videolar: {len(selected)}")
    return selected, sources


# ===================== O'ZBEKCHA ERKAK OVOZI =====================
async def make_voice(text):
    communicate = edge_tts.Communicate(
        text=text,
        voice=VOICE,
        rate="-5%",
        volume="+0%"
    )
    await communicate.save(AUDIO_FILE)


# ===================== MATNLI RASMLAR =====================
def get_font(size):
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    ]

    for path in paths:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)

    return ImageFont.load_default()


def make_banner(text, filename, height=180):
    img = Image.new(
        "RGBA",
        (W, height),
        (0, 0, 0, 0)
    )

    draw = ImageDraw.Draw(img)

    draw.rounded_rectangle(
        (15, 10, W - 15, height - 10),
        radius=25,
        fill=(0, 0, 0, 210)
    )

    font = get_font(38)
    lines = textwrap.wrap(text, width=27)[:3]

    line_heights = []

    for line in lines:
        box = draw.textbbox((0, 0), line, font=font)
        line_heights.append((line, box[2] - box[0]))

    y = max(15, (height - len(lines) * 48) // 2)

    for line, width in line_heights:
        draw.text(
            ((W - width) / 2, y),
            line,
            font=font,
            fill="white"
        )
        y += 48

    img.save(filename)
    return filename


def make_subtitle(text, filename):
    img = Image.new(
        "RGBA",
        (W, 220),
        (0, 0, 0, 0)
    )

    draw = ImageDraw.Draw(img)

    draw.rounded_rectangle(
        (12, 5, W - 12, 210),
        radius=20,
        fill=(0, 0, 0, 205)
    )

    font = get_font(31)
    y = 20

    for line in textwrap.wrap(text, width=34)[:4]:
        draw.text(
            (28, y),
            line,
            font=font,
            fill="white"
        )
        y += 43

    img.save(filename)
    return filename


# ===================== VERTIKAL VIDEO MONTAJ =====================
def create_video(script, title, video_paths):
    audio = AudioFileClip(AUDIO_FILE)
    duration = audio.duration

    if duration <= 0:
        audio.close()
        raise ValueError("Ovoz davomiyligi noto'g'ri")

    sources = []
    segments = []
    overlays = []

    base = None
    final = None

    try:
        scene_length = 4
        current_time = 0
        index = 0

        while current_time < duration:
            path = video_paths[index % len(video_paths)]
            source = VideoFileClip(path, audio=False)
            sources.append(source)

            if source.duration > scene_length + 1:
                start = random.uniform(
                    0,
                    source.duration - scene_length
                )
            else:
                start = 0

            end = min(
                start + scene_length,
                source.duration
            )

            part = source.subclip(start, end)

            if part.w / part.h < W / H:
                part = part.resize(width=W)
            else:
                part = part.resize(height=H)

            part = part.crop(
                x_center=part.w / 2,
                y_center=part.h / 2,
                width=W,
                height=H
            )

            remaining = duration - current_time

            if part.duration > remaining:
                part = part.subclip(0, remaining)

            segments.append(part)
            current_time += part.duration
            index += 1

        base = concatenate_videoclips(
            segments,
            method="chain"
        ).set_duration(duration)

        base = base.set_audio(audio)

        # Sarlavha
        title_file = make_banner(title, "title.png")

        overlays.append(
            ImageClip(title_file)
            .set_start(0)
            .set_duration(min(5, duration))
            .set_position(("center", 70))
        )

        # Subtitrlar
        words = script.split()
        chunks = [
            words[i:i + 8]
            for i in range(0, len(words), 8)
        ]

        caption_duration = duration / max(1, len(chunks))

        for i, chunk in enumerate(chunks):
            filename = f"subtitle_{i}.png"

            make_subtitle(
                " ".join(chunk),
                filename
            )

            overlays.append(
                ImageClip(filename)
                .set_start(i * caption_duration)
                .set_duration(caption_duration)
                .set_position(("center", 980))
            )

        # Yakuniy yozuv
        if VIDEO_PART == 1:
            end_text = "DAVOMI KEYINGI QISMDA..."
        else:
            end_text = "HIKOYA YAKUNLANDI!"

        end_file = make_banner(
            end_text,
            "ending.png",
            height=200
        )

        overlays.append(
            ImageClip(end_file)
            .set_start(max(0, duration - min(4, duration)))
            .set_duration(min(4, duration))
            .set_position(("center", 520))
        )

        final = CompositeVideoClip(
            [base] + overlays,
            size=(W, H)
        ).set_audio(audio)

        log("Video MP4 formatida saqlanmoqda...")

        final.write_videofile(
            VIDEO_FILE,
            fps=FPS,
            codec="libx264",
            audio_codec="aac",
            preset="ultrafast",
            threads=4,
            bitrate="1800k",
            logger="bar"
        )

        log("Video tayyor!")

    finally:
        if final:
            final.close()

        if base:
            base.close()

        for source in sources:
            try:
                source.close()
            except Exception:
                pass

        audio.close()


# ===================== YOUTUBE'GA YUKLASH =====================
def upload_to_youtube(title, sources):
    credentials = Credentials(
        None,
        refresh_token=os.environ["YOUTUBE_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["YOUTUBE_CLIENT_ID"],
        client_secret=os.environ["YOUTUBE_CLIENT_SECRET"],
        scopes=[
            "https://www.googleapis.com/auth/youtube.upload"
        ]
    )

    youtube = build(
        "youtube",
        "v3",
        credentials=credentials,
        cache_discovery=False
    )

    description = (
        "O'zbek tilidagi sirli hikoya.\n"
        "Hikoya davom etadi!\n"
        "#shorts #uzbek #sirli #hikoya\n\n"
        "Video lavhalari: Pixabay\n"
        + "\n".join(sources)
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body={
            "snippet": {
                "title": f"{title} | {VIDEO_PART}-qism #shorts",
                "description": description[:4900],
                "tags": [
                    "uzbek",
                    "sirli hikoya",
                    "shorts",
                    "uzbekcha"
                ],
                "categoryId": "22"
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False
            }
        },
        media_body=MediaFileUpload(
            VIDEO_FILE,
            mimetype="video/mp4",
            resumable=True,
            chunksize=8 * 1024 * 1024
        )
    )

    response = None

    while response is None:
        status, response = request.next_chunk()

        if status:
            log(
                "YouTube yuklash: "
                + str(int(status.progress() * 100))
                + "%"
            )

    log("YouTube video ID: " + response["id"])


# ===================== ASOSIY DASTUR =====================
def main():
    log("YOUTUBE SHORTS AVTOMATIK TIZIM")
    log(f"Video qismi: {VIDEO_PART}")

    log("1. Hikoya olinmoqda...")
    title, story, queries = create_script()

    if VIDEO_PART == 1:
        ending = "Davomi keyingi qismda..."
    else:
        ending = "Hikoya yakunlandi!"

    full_text = story.rstrip() + " " + ending

    log("2. Sardor erkak ovozida audio yaratilmoqda...")
    asyncio.run(make_voice(full_text))

    log("3. Pixabay videolari qidirilmoqda...")
    video_paths, sources = get_real_videos(queries)

    log("4. Video montaj qilinmoqda...")
    create_video(full_text, title, video_paths)

    log("5. YouTube'ga yuklanmoqda...")
    upload_to_youtube(title, sources)

    log("HAMMA JARAYON TUGADI!")


if __name__ == "__main__":
    main()
