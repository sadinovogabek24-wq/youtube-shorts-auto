
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
    VideoFileClip,
    AudioFileClip,
    ImageClip,
    CompositeVideoClip,
    concatenate_videoclips
)

import edge_tts
from google import genai
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload


# ==========================================
# SOZLAMALAR
# ==========================================

W = 720
H = 1280
FPS = 20

VOICE = "uz-UZ-SardorNeural"

VIDEO_PART = int(
    os.getenv("VIDEO_PART", os.getenv("EPISODE_PART", "1"))
)

EPISODE_FILE = "episode.json"
CACHE_FILE = "pixabay_cache.json"
AUDIO_FILE = "voice.mp3"
VIDEO_FILE = "video.mp4"

PIXABAY_KEY = os.environ["PIXABAY_API_KEY"]

client = genai.Client(
    api_key=os.environ["GEMINI_API_KEY"]
)


def log(message):
    print(message, flush=True)


# ==========================================
# GEMINI 3.5 BIRINCHI, 3.8 ZAXIRA
# ==========================================

def gemini_text(prompt):

    models = [
        "gemini-3.5-flash-lite",
        "gemini-3.8-flash"
    ]

    last_error = None

    for model in models:
        try:
            log("Gemini ishga tushdi: " + model)

            response = client.models.generate_content(
                model=model,
                contents=prompt
            )

            result = response.text

            if not result:
                raise ValueError("Gemini bo'sh javob berdi")

            log("Ishlagan model: " + model)
            return result

        except Exception as error:
            last_error = error
            log(f"{model} xatosi: {error}")
            log("Zaxira model tekshirilmoqda...")

    raise RuntimeError(
        "Gemini modellarida xato: " + str(last_error)
    )


def extract_json(raw):

    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?", "", raw)
    raw = re.sub(r"```$", "", raw.strip())

    match = re.search(r"\{.*\}", raw, re.S)

    if not match:
        raise ValueError("JSON topilmadi")

    return json.loads(match.group())


# ==========================================
# HIKOYA VA VIDEO QIDIRUV SO'ZLARI
# ==========================================

def create_script():

    if VIDEO_PART == 1:

        prompt = """
        O'zbek tilida juda qiziqarli, sirli va hayajonli hikoya yoz.

        Ikki qismli hikoya bo'lsin.

        part1:
        140-180 ta so'z.
        Boshidan qiziqarli bo'lsin.
        Oxirida kuchli sirli to'xtash bo'lsin.

        part2:
        140-180 ta so'z.
        Birinchi qismning bevosita davomi bo'lsin.
        Sirni ochib bersin va hikoyani yakunlasin.

        Har ikki qism uchun alohida 10-12 ta inglizcha
        video qidiruv iborasi yoz.

        Qidiruv iboralari Pixabay videolaridan haqiqiy
        harakatlanuvchi lavhalarni topishga mos bo'lsin.
        Masalan: abandoned house, man walking at night,
        dark forest, mysterious road, old door.

        Faqat JSON qaytar:

        {
          "title": "Hikoya nomi",
          "part1": "Birinchi qism",
          "part2": "Ikkinchi qism",
          "queries1": ["abandoned house", "dark forest"],
          "queries2": ["old house", "man walking"]
        }
        """

        story = extract_json(gemini_text(prompt))

        required = [
            "title", "part1", "part2",
            "queries1", "queries2"
        ]

        for key in required:
            if key not in story:
                raise ValueError("Hikoya ma'lumoti yetishmaydi: " + key)

        with open(EPISODE_FILE, "w", encoding="utf-8") as f:
            json.dump(story, f, ensure_ascii=False, indent=2)

        return story["title"], story["part1"], story["queries1"]

    if VIDEO_PART == 2:

        if not os.path.exists(EPISODE_FILE):
            raise FileNotFoundError(
                "episode.json topilmadi. 1-qism fayli saqlanganini tekshiring."
            )

        with open(EPISODE_FILE, "r", encoding="utf-8") as f:
            story = json.load(f)

        return story["title"], story["part2"], story["queries2"]

    raise ValueError("VIDEO_PART faqat 1 yoki 2 bo'lishi kerak")


# ==========================================
# PIXABAY 24 SOATLIK KESH
# ==========================================

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
        log("Keshdan olindi: " + query)
        return saved.get("hits", [])

    log("Pixabay qidiruvi: " + query)

    url = "https://pixabay.com/api/videos/"

    params = {
        "key": PIXABAY_KEY,
        "q": query,
        "video_type": "film",
        "per_page": 10,
        "safesearch": "true",
        "order": "popular"
    }

    response = requests.get(
        url,
        params=params,
        timeout=30
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"Pixabay xatosi {response.status_code}: "
            + response.text[:300]
        )

    data = response.json()
    hits = data.get("hits", [])

    cache[query] = {
        "time": now,
        "hits": hits
    }

    save_cache(cache)

    return hits


# ==========================================
# HAQIQIY VIDEOLARNI TOPISH VA YUKLASH
# ==========================================

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
        raise ValueError("Video fayli juda kichik")

    return filename


def get_real_videos(queries):

    cache = load_cache()
    selected = []
    used_ids = set()
    sources = []

    # Ko'pi bilan 12 ta turli videolavha
    for query in queries[:12]:

        if len(selected) >= 12:
            break

        try:
            hits = search_pixabay(query, cache)

            random.shuffle(hits)

            for hit in hits:

                if hit["id"] in used_ids:
                    continue

                videos = hit.get("videos", {})

                video_data = (
                    videos.get("medium")
                    or videos.get("small")
                    or videos.get("tiny")
                )

                if not video_data or not video_data.get("url"):
                    continue

                filename = f"stock_{len(selected)}.mp4"

                log("Video yuklanmoqda: " + query)

                try:
                    download_video(
                        video_data["url"],
                        filename
                    )
                except Exception as error:
                    log("Yuklash xatosi: " + str(error))
                    continue

                used_ids.add(hit["id"])
                selected.append(filename)
                sources.append(hit.get("pageURL", ""))

                break

        except Exception as error:
            log("Qidiruv o'tkazib yuborildi: " + str(error))

    if not selected:
        raise RuntimeError(
            "Pixabay'dan videolar topilmadi. "
            "API kalit va internetni tekshiring."
        )

    save_cache(cache)

    log(f"Topilgan haqiqiy videolar: {len(selected)}")

    return selected, sources


# ==========================================
# O'ZBEKCHA OVOZ
# ==========================================

async def make_voice(text):

    communicate = edge_tts.Communicate(
        text=text,
        voice=VOICE,
        rate="-5%",
        volume="+0%"
    )

    await communicate.save(AUDIO_FILE)


# ==========================================
# SHRIFT VA YOZUVLAR
# ==========================================

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
        fill=(0, 0, 0, 205)
    )

    font = get_font(38)

    lines = textwrap.wrap(text, width=27)[:3]

    y = 25

    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        width = bbox[2] - bbox[0]

        draw.text(
            ((W - width) / 2, y),
            line,
            font=font,
            fill=(255, 255, 255, 255)
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
    lines = textwrap.wrap(text, width=34)[:4]

    y = 20

    for line in lines:
        draw.text(
            (28, y),
            line,
            font=font,
            fill="white"
        )
        y += 43

    img.save(filename)
    return filename


# ==========================================
# VIDEO KADRLARINI VERTIKAL QILISH
# ==========================================

def prepare_segment(path, start, duration):

    clip = VideoFileClip(path, audio=False)

    if clip.duration < 1:
        clip.close()
        raise ValueError("Video davomiyligi juda qisqa")

    start = min(start, max(0, clip.duration - 0.5))
    end = min(start + duration, clip.duration)

    if end - start < 0.5:
        clip.close()
        raise ValueError("Video kesimi juda qisqa")

    part = clip.subclip(start, end)

    # 9:16 vertikal formatga moslashtirish
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

    return clip, part


# ==========================================
# VIDEO MONTAJ
# ==========================================

def create_video(script, title, video_paths):

    log("Ovoz davomiyligi tekshirilmoqda...")

    audio = AudioFileClip(AUDIO_FILE)
    duration = audio.duration

    if duration <= 0:
        audio.close()
        raise ValueError("Ovoz davomiyligi noto'g'ri")

    sources = []
    segments = []

    try:

        # Har bir lavha taxminan 4 soniya
        scene_length = 4
        current_time = 0
        index = 0

        while current_time < duration:

            path = video_paths[index % len(video_paths)]

            log(
                f"Harakatli kadr {index + 1}: "
                f"{current_time:.1f}/{duration:.1f} soniya"
            )

            source = VideoFileClip(path, audio=False)
            sources.append(source)

            start = 0

            if source.duration > scene_length + 1:
                start = random.uniform(
                    0,
                    source.duration - scene_length
                )

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

        log("Harakatli lavhalar birlashtirilmoqda...")

        base = concatenate_videoclips(
            segments,
            method="chain"
        )

        base = base.set_duration(duration)
        base = base.set_audio(audio)

        overlays = []

        # Mavzu nomi
        title_file = make_banner(
            title,
            "title.png"
        )

        title_clip = (
            ImageClip(title_file)
            .set_start(0)
            .set_duration(min(5, duration))
            .set_position(("center", 70))
        )

        overlays.append(title_clip)

        # Ovozga mos subtitrlar
        words = script.split()
        chunks = [
            words[i:i + 8]
            for i in range(0, len(words), 8)
        ]

        # Oxirgi qo'shimcha jumla ham subtitrga kiradi
        caption_duration = duration / max(1, len(chunks))

        for i, chunk in enumerate(chunks):

            caption = " ".join(chunk)

            filename = f"subtitle_{i}.png"

            make_subtitle(caption, filename)

            start = i * caption_duration

            subtitle_clip = (
                ImageClip(filename)
                .set_start(start)
                .set_duration(caption_duration)
                .set_position(("center", 980))
            )

            overlays.append(subtitle_clip)

        # Yakuniy yozuv
        if VIDEO_PART == 1:
            end_text = "DAVOMI IKKINCHI QISMDA!"
        else:
            end_text = "HIKOYA YAKUNLANDI!"

        end_file = make_banner(
            end_text,
            "ending.png",
            height=200
        )

        end_clip = (
            ImageClip(end_file)
            .set_start(max(0, duration - 4))
            .set_duration(min(4, duration))
            .set_position(("center", 520))
        )

        overlays.append(end_clip)

        final = CompositeVideoClip(
            [base] + overlays,
            size=(W, H)
        )

        final = final.set_audio(audio)

        log("MP4 video saqlanmoqda...")

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

        final.close()
        base.close()

        log("Video tayyor!")

    finally:

        for source in sources:
            try:
                source.close()
            except Exception:
                pass

        audio.close()


# ==========================================
# YOUTUBE GA YUKLASH
# ==========================================

def upload_to_youtube(title, sources):

    log("YouTube'ga ulanish...")

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

    credits = "\n".join(
        source for source in sources if source
    )

    description = (
        "O'zbek tilidagi sirli hikoya.\n"
        "Hikoya davom etadi!\n"
        "#shorts #uzbek #sirli #hikoya\n\n"
        "Video lavhalari: Pixabay\n"
        + credits
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


# ==========================================
# ASOSIY DASTUR
# ==========================================

def main():

    log("YOUTUBE SHORTS AVTOMATIK TIZIM")
    log("Video qismi: " + str(VIDEO_PART))

    log("1. Hikoya yaratilmoqda...")

    title, story, queries = create_script()

    if VIDEO_PART == 1:
        ending = "Davomi ikkinchi qismda!"
    else:
        ending = "Hikoya yakunlandi!"

    full_text = story + " " + ending

    log("2. O'zbekcha ovoz yaratilmoqda...")

    asyncio.run(make_voice(full_text))

    log("3. Pixabay'dan haqiqiy videolar qidirilmoqda...")

    video_paths, sources = get_real_videos(queries)

    log("4. Harakatli video montaj qilinmoqda...")

    create_video(full_text, title, video_paths)

    log("5. YouTube'ga yuklanmoqda...")

    upload_to_youtube(title, sources)

    log("HAMMA JARAYON TUGADI!")


if __name__ == "__main__":
    main()
