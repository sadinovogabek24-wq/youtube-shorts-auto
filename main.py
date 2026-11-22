
import os
import re
import json
import time
import random
import asyncio
from pathlib import Path

import requests
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import edge_tts
from google import genai
from moviepy.editor import (
    AudioFileClip, VideoFileClip, VideoClip,
    concatenate_videoclips, vfx
)

WIDTH, HEIGHT = 1080, 1920
FPS = 24
VOICE = "uz-UZ-SardorNeural"
OUTPUT = "shorts.mp4"
AUDIO_FILE = "voice.mp3"
EPISODE_FILE = Path("episode.json")

TEXT_MODEL = "gemini-3.5-flash-lite"
BACKUP_TEXT_MODEL = "gemini-3.8-flash"

PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY", "").strip()

DEFAULT_VIDEO_QUERIES = [
    "mysterious forest night",
    "abandoned house night",
    "dark road night",
    "man silhouette walking",
]


def required_env(name):
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} GitHub Secret topilmadi.")
    return value


def clean_json(text):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    match = re.search(r"\{.*\}", text, flags=re.S)
    if not match:
        raise ValueError("Gemini javobidan JSON topilmadi.")
    return json.loads(match.group(0))


def gemini_json(prompt):
    client = genai.Client(api_key=required_env("GEMINI_API_KEY"))
    last_error = None

    for model in (TEXT_MODEL, BACKUP_TEXT_MODEL):
        for attempt in range(4):
            try:
                print(f"Gemini modeli: {model}; urinish {attempt + 1}/4")
                response = client.models.generate_content(
                    model=model,
                    contents=prompt
                )
                return clean_json(response.text)
            except Exception as exc:
                last_error = exc
                message = str(exc).lower()
                retryable = any(word in message for word in (
                    "503", "unavailable", "429", "resource_exhausted",
                    "500", "internal", "timeout", "temporarily"
                ))
                if retryable and attempt < 3:
                    wait = min(45, 5 * (2 ** attempt))
                    print(f"Gemini band. {wait} soniya kutamiz...")
                    time.sleep(wait)
                    continue
                break

    raise RuntimeError(f"Gemini hikoya yarata olmadi: {last_error}")


def create_episode():
    prompt = """
O'zbek tilida ikki qismli sirli YouTube Shorts hikoyasi yoz.
Nomi: YO'QOLGANLAR SIRI.
Bosh qahramon 19 yoshli Jasur. Shaharchada odamlar izsiz yo'qoladi.

Talablar:
- Ikki qism bitta uzluksiz hikoya bo'lsin.
- Har bir qism 230-300 so'z bo'lsin.
- Birinchi jumlalar qiziqarli bo'lsin.
- 1-qism sirni ochmasin va kuchli cliffhanger bilan tugasin.
- 1-qism oxiri: Davomi 2-qismda.
- 2-qism birinchi qism tugagan joydan davom etsin.
- 2-qismda sir to'liq ochilsin.
- Ravon, sodda o'zbek tilida yoz.
- Zo'ravonlikni batafsil tasvirlama.
- Har qism uchun 4 ta inglizcha video qidiruv so'zi yoz.

Faqat JSON qaytar:
{
 "title": "Yo'qolganlar siri",
 "part1": "Birinchi qism",
 "part2": "Ikkinchi qism",
 "visuals1": ["night forest", "old house night", "man walking", "dark road"],
 "visuals2": ["underground tunnel", "old basement", "mysterious door", "sunrise town"]
}
"""
    episode = gemini_json(prompt)

    for key in ("part1", "part2"):
        if not isinstance(episode.get(key), str) or len(episode[key].split()) < 100:
            raise ValueError(f"{key} matni bo'sh yoki juda qisqa.")

    episode.setdefault("title", "Yo'qolganlar siri")
    episode.setdefault("visuals1", DEFAULT_VIDEO_QUERIES)
    episode.setdefault("visuals2", DEFAULT_VIDEO_QUERIES)
    return episode


async def _make_voice(text):
    communicate = edge_tts.Communicate(
        text=text,
        voice=VOICE,
        rate="-7%",
        volume="+0%"
    )
    await communicate.save(AUDIO_FILE)


def create_voice(text):
    asyncio.run(_make_voice(text))


def find_font(size=46):
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    ]
    for path in paths:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def sentence_timings(text, duration):
    sentences = [
        s.strip() for s in re.split(r"(?<=[.!?])\s+", text)
        if s.strip()
    ]
    total = sum(len(s) for s in sentences) or 1
    result = []
    cursor = 0.0

    for sentence in sentences:
        span = duration * len(sentence) / total
        result.append((sentence, cursor, cursor + span))
        cursor += span

    return result


def caption_for_time(timings, t):
    for sentence, start, end in timings:
        if start <= t < end:
            return sentence
    return ""


def draw_caption(frame, caption):
    if not caption:
        return frame

    image = Image.fromarray(frame).convert("RGBA")
    draw = ImageDraw.Draw(image, "RGBA")
    font = find_font(46)

    words = caption.split()
    lines = []
    line = ""

    for word in words:
        test = (line + " " + word).strip()
        if draw.textbbox((0, 0), test, font=font)[2] < WIDTH - 150:
            line = test
        else:
            if line:
                lines.append(line)
            line = word

    if line:
        lines.append(line)

    lines = lines[:3]
    heights = [
        draw.textbbox((0, 0), s, font=font)[3]
        for s in lines
    ]
    total_h = sum(heights) + 18 * max(0, len(lines) - 1)
    y = int(HEIGHT * 0.70)

    draw.rounded_rectangle(
        (45, y - 28, WIDTH - 45, y + total_h + 40),
        radius=26,
        fill=(0, 0, 0, 170),
        outline=(255, 205, 110, 220),
        width=3
    )

    for text, height in zip(lines, heights):
        box = draw.textbbox((0, 0), text, font=font, stroke_width=2)
        x = (WIDTH - (box[2] - box[0])) // 2
        draw.text(
            (x, y), text,
            font=font,
            fill=(255, 255, 255, 255),
            stroke_width=2,
            stroke_fill=(0, 0, 0, 255)
        )
        y += height + 18

    return np.asarray(image.convert("RGB"))


def download_pixabay_clip(query, index):
    if not PIXABAY_API_KEY:
        return None

    try:
        response = requests.get(
            "https://pixabay.com/api/videos/",
            params={
                "key": PIXABAY_API_KEY,
                "q": query,
                "video_type": "film",
                "orientation": "vertical",
                "safesearch": "true",
                "per_page": 8
            },
            timeout=30
        )
        response.raise_for_status()
        hits = response.json().get("hits", [])

        if not hits:
            return None

        hit = random.choice(hits[:min(5, len(hits))])
        videos = hit.get("videos", {})
        item = videos.get("medium") or videos.get("small") or videos.get("large")

        if not item or not item.get("url"):
            return None

        path = Path(f"scene_{index}.mp4")

        with requests.get(item["url"], stream=True, timeout=90) as download:
            download.raise_for_status()
            with path.open("wb") as file:
                for chunk in download.iter_content(1024 * 256):
                    if chunk:
                        file.write(chunk)

        if path.stat().st_size < 10000:
            path.unlink(missing_ok=True)
            return None

        print(f"Pixabay lavhasi olindi: {query}")
        return str(path)

    except Exception as exc:
        print(f"Pixabay xatosi: {exc}")
        return None


def make_fallback_scene(seed):
    rng = random.Random(seed)

    top = np.array([7, 15, 36], dtype=np.float32)
    bottom = np.array([38, 67, 91], dtype=np.float32)
    gradient = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)

    for y in range(HEIGHT):
        ratio = y / HEIGHT
        gradient[y, :, :] = (
            top * (1 - ratio) + bottom * ratio
        ).astype(np.uint8)

    image = Image.fromarray(gradient, "RGB").convert("RGBA")
    draw = ImageDraw.Draw(image, "RGBA")

    moon_x = rng.randint(250, 820)
    moon_y = rng.randint(350, 700)

    draw.ellipse(
        (moon_x - 115, moon_y - 115, moon_x + 115, moon_y + 115),
        fill=(230, 205, 150, 210)
    )

    for layer, base_y in enumerate((1150, 1390, 1610)):
        points = [(0, HEIGHT)]
        x = 0

        while x < WIDTH:
            points.append((x, base_y + rng.randint(-120, 140)))
            x += rng.randint(80, 160)

        points.append((WIDTH, HEIGHT))
        draw.polygon(
            points,
            fill=(7 + layer * 3, 13 + layer * 3, 23 + layer * 4, 255)
        )

    for x in range(-30, WIDTH, 140):
        w = rng.randint(55, 115)
        h = rng.randint(170, 390)

        draw.rectangle(
            (x, 1630 - h, x + w, 1630),
            fill=(3, 6, 12, 255)
        )

        draw.polygon(
            [
                (x - 12, 1630 - h),
                (x + w // 2, 1580 - h),
                (x + w + 12, 1630 - h)
            ],
            fill=(4, 7, 13, 255)
        )

    return image.convert("RGB")


def make_fallback_clip(index, duration):
    still = make_fallback_scene(index + 100)
    zoom = still.resize((int(WIDTH * 1.15), int(HEIGHT * 1.15)))
    max_x = zoom.width - WIDTH
    max_y = zoom.height - HEIGHT

    def frame(t):
        p = t / max(duration, 0.01)
        x = int(max_x * p)
        y = int(max_y * (1 - p))
        return np.asarray(
            zoom.crop((x, y, x + WIDTH, y + HEIGHT))
        )

    return VideoClip(make_frame=frame, duration=duration)


def fit_vertical(clip):
    scale = max(WIDTH / clip.w, HEIGHT / clip.h)
    clip = clip.resize(scale)

    x1 = max(0, (clip.w - WIDTH) / 2)
    y1 = max(0, (clip.h - HEIGHT) / 2)

    return clip.crop(
        x1=x1, y1=y1,
        x2=x1 + WIDTH, y2=y1 + HEIGHT
    )


def create_video(story, visual_queries):
    audio = AudioFileClip(AUDIO_FILE)
    duration = audio.duration
    timings = sentence_timings(story, duration)

    queries = [
        q for q in visual_queries
        if isinstance(q, str) and q.strip()
    ]

    if len(queries) < 4:
        queries = DEFAULT_VIDEO_QUERIES

    segment_duration = duration / 4
    clips = []

    try:
        for i, query in enumerate(queries[:4]):
            path = download_pixabay_clip(query, i)

            if path:
                try:
                    clip = VideoFileClip(path, audio=False)
                    if clip.duration < 1:
                        clip.close()
                        raise ValueError("Lavha juda qisqa.")

                    clip = fit_vertical(clip)
                    clip = clip.fx(vfx.loop, duration=segment_duration)
                    clips.append(clip)
                    continue

                except Exception as exc:
                    print("Lavhani ochishda xato:", exc)

            clips.append(make_fallback_clip(i, segment_duration))

        background = concatenate_videoclips(clips, method="compose")
        background = background.set_duration(duration)

        def frame(t):
            base = background.get_frame(t)
            caption = caption_for_time(timings, t)
            return draw_caption(base, caption)

        final = VideoClip(
            make_frame=frame,
            duration=duration
        ).set_audio(audio)

        final.write_videofile(
            OUTPUT,
            fps=FPS,
            codec="libx264",
            audio_codec="aac",
            bitrate="4500k",
            preset="veryfast",
            threads=4,
            ffmpeg_params=[
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart"
            ]
        )

        final.close()
        background.close()

    finally:
        audio.close()
        for clip in clips:
            try:
                clip.close()
            except Exception:
                pass


def upload_to_youtube(part):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    credentials = Credentials(
        token=None,
        refresh_token=required_env("YOUTUBE_REFRESH_TOKEN"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=required_env("YOUTUBE_CLIENT_ID"),
        client_secret=required_env("YOUTUBE_CLIENT_SECRET"),
        scopes=["https://www.googleapis.com/auth/youtube.upload"]
    )

    youtube = build("youtube", "v3", credentials=credentials)

    body = {
        "snippet": {
            "title": f"YO'QOLGANLAR SIRI — {part}-QISM 😱 #shorts",
            "description": (
                "Sirli hikoyaning davomi kanalimizda!\n"
                "#shorts #uzbek #sirli #hikoya"
            ),
            "tags": [
                "shorts", "uzbek", "sirli hikoya",
                "mystery", "uzbek shorts"
            ],
            "categoryId": "22"
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False
        }
    }

    media = MediaFileUpload(
        OUTPUT,
        mimetype="video/mp4",
        resumable=True,
        chunksize=8 * 1024 * 1024
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media
    )

    response = None

    while response is None:
        status, response = request.next_chunk()
        if status:
            print(
                f"YouTube yuklanmoqda: "
                f"{int(status.progress() * 100)}%"
            )

    print("YouTube video ID:", response.get("id"))


def main():
    part = os.getenv("EPISODE_PART", "1").strip()

    if part not in ("1", "2"):
        raise ValueError("EPISODE_PART faqat 1 yoki 2 bo'lishi kerak.")

    if part == "1":
        print("Yangi ikki qismli hikoya yaratilmoqda...")
        episode = create_episode()

        EPISODE_FILE.write_text(
            json.dumps(episode, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    else:
        print("Saqlangan hikoyaning 2-qismi olinmoqda...")

        if not EPISODE_FILE.exists():
            raise FileNotFoundError(
                "episode.json topilmadi. Avval 1-qismni ishga tushiring."
            )

        episode = json.loads(
            EPISODE_FILE.read_text(encoding="utf-8")
        )

    story_key = "part1" if part == "1" else "part2"
    visuals_key = "visuals1" if part == "1" else "visuals2"

    story = episode[story_key]
    visuals = episode.get(visuals_key, DEFAULT_VIDEO_QUERIES)

    Path("story.txt").write_text(story, encoding="utf-8")

    print("O'zbekcha erkak ovozi yaratilmoqda...")
    create_voice(story)

    print("9:16 video tayyorlanmoqda...")
    create_video(story, visuals)

    print("YouTube kanaliga yuklanmoqda...")
    upload_to_youtube(part)

    print(f"TAYYOR: {part}-qism yuklandi.")


if __name__ == "__main__":
    main()
