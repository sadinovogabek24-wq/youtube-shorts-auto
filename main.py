
import os
import re
import json
import asyncio
import textwrap
import random

from PIL import Image, ImageDraw, ImageFont

# ==========================================
# SOZLAMALAR
# ==========================================

VIDEO_WIDTH = 720
VIDEO_HEIGHT = 1280
FPS = 20

VOICE = "uz-UZ-SardorNeural"

VIDEO_PART = int(
    os.getenv("VIDEO_PART", os.getenv("EPISODE_PART", "1"))
)

EPISODE_FILE = "episode.json"
AUDIO_FILE = "voice.mp3"
VIDEO_FILE = "video.mp4"

from moviepy.editor import (
    ImageClip,
    AudioFileClip,
    concatenate_videoclips
)

import edge_tts
from google import genai
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

client = genai.Client(
    api_key=os.environ["GEMINI_API_KEY"]
)


def log(message):
    print(message, flush=True)


# ==========================================
# GEMINI 3.5 -> 3.8
# ==========================================

def gemini_text(prompt):
    models = [
        "gemini-3.5-flash-lite",
        "gemini-3.8-flash"
    ]

    last_error = None

    for model_name in models:
        try:
            log("Gemini ishga tushmoqda: " + model_name)

            response = client.models.generate_content(
                model=model_name,
                contents=prompt
            )

            result = response.text

            if not result:
                raise ValueError("Gemini bo'sh javob berdi")

            log("Ishlagan model: " + model_name)
            return result

        except Exception as error:
            last_error = error
            log(f"{model_name} xatosi: {error}")
            log("Zaxira model sinab ko'riladi...")

    raise RuntimeError(str(last_error))


# ==========================================
# JSON
# ==========================================

def extract_json(raw_text):
    cleaned = raw_text.strip()
    cleaned = re.sub(r"^```(?:json)?", "", cleaned)
    cleaned = re.sub(r"```$", "", cleaned.strip())

    match = re.search(r"\{.*\}", cleaned, re.S)

    if not match:
        raise ValueError("JSON topilmadi")

    return json.loads(match.group())


# ==========================================
# HIKOYA
# ==========================================

def create_script():

    if VIDEO_PART == 1:

        prompt = """
        O'zbek tilida juda qiziqarli sirli hikoya yoz.

        Hikoya ikki qismdan iborat bo'lsin.

        Birinchi qism:
        - 100 dan 250 tagacha so'z.
        - Boshidan tomoshabinni qiziqtirsin.
        - Sirli voqea bilan boshlansin.
        - Oxirida kuchli hayajonli tugash bo'lsin.

        Ikkinchi qism:
        - 100 dan 250 tagacha so'z.
        - Birinchi qismning bevosita davomi bo'lsin.
        - Sirning sababini ochib bersin.
        - Yakuni qiziqarli bo'lsin.

        Tabiiy va ravon o'zbek tilida yoz.
        Ovoz chiqarib o'qishga mos bo'lsin.

        Faqat JSON formatida javob ber:

        {
          "title": "Hikoya nomi",
          "part1": "Birinchi qism",
          "part2": "Ikkinchi qism"
        }
        """

        raw = gemini_text(prompt)
        story = extract_json(raw)

        for key in ["title", "part1", "part2"]:
            if not story.get(key):
                raise ValueError("Hikoya ma'lumotlari to'liq emas")

        with open(EPISODE_FILE, "w", encoding="utf-8") as file:
            json.dump(
                story,
                file,
                ensure_ascii=False,
                indent=2
            )

        return story["title"], story["part1"]

    elif VIDEO_PART == 2:

        if not os.path.exists(EPISODE_FILE):
            raise FileNotFoundError("episode.json topilmadi")

        with open(EPISODE_FILE, "r", encoding="utf-8") as file:
            story = json.load(file)

        return story["title"], story["part2"]

    raise ValueError("VIDEO_PART 1 yoki 2 bo'lishi kerak")


# ==========================================
# MATNNI BO'LISH
# ==========================================

def split_text(text):
    words = text.split()

    if not words:
        raise ValueError("Hikoya bo'sh")

    chunk_size = max(1, len(words) // 3)

    return [
        " ".join(words[:chunk_size]),
        " ".join(words[chunk_size:chunk_size * 2]),
        " ".join(words[chunk_size * 2:])
    ]


# ==========================================
# OVOZ
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
# SHRIFT
# ==========================================

def get_font(size):
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"
    ]

    for path in paths:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)

    return ImageFont.load_default()


# ==========================================
# KADR YARATISH
# ==========================================

def make_frame(number, subtitle):

    random.seed(number)

    # Asl rasm 1080x1920 chiziladi,
    # so'ng 720x1280 ga kichraytiriladi.

    img = Image.new(
        "RGB",
        (1080, 1920),
        (5, 8, 25)
    )

    draw = ImageDraw.Draw(img)

    for _ in range(120):
        x = random.randint(0, 1080)
        y = random.randint(0, 1250)
        r = random.randint(1, 3)

        draw.ellipse(
            (x-r, y-r, x+r, y+r),
            fill=(190, 195, 220)
        )

    draw.ellipse(
        (760, 170, 960, 370),
        fill=(225, 220, 180)
    )

    draw.polygon(
        [(0, 1250), (280, 750), (600, 1250)],
        fill=(18, 28, 55)
    )

    draw.polygon(
        [(350, 1250), (750, 680), (1080, 1250)],
        fill=(25, 35, 65)
    )

    if number == 1:

        draw.rectangle(
            (250, 1050, 820, 1600),
            fill=(12, 15, 25)
        )

        draw.polygon(
            [(190, 1050), (530, 790), (880, 1050)],
            fill=(45, 25, 35)
        )

    elif number == 2:

        draw.rectangle(
            (150, 900, 900, 1600),
            fill=(15, 18, 30)
        )

        draw.polygon(
            [(100, 900), (520, 620), (950, 900)],
            fill=(40, 25, 40)
        )

    else:

        draw.rectangle(
            (280, 850, 800, 1650),
            fill=(18, 20, 30)
        )

        draw.rectangle(
            (430, 1050, 650, 1650),
            fill=(65, 35, 25)
        )

        draw.ellipse(
            (600, 1300, 625, 1325),
            fill=(230, 190, 90)
        )

    for x in [350, 620]:
        draw.rectangle(
            (x, 1150, x+90, 1290),
            fill=(220, 150, 55)
        )

    draw.text(
        (65, 90),
        f"SAHNA {number}",
        font=get_font(48),
        fill=(255, 220, 150)
    )

    draw.rounded_rectangle(
        (45, 1510, 1035, 1840),
        radius=30,
        fill=(0, 0, 0)
    )

    subtitle_font = get_font(43)

    lines = textwrap.wrap(subtitle, width=32)[:5]

    y = 1570

    for line in lines:
        draw.text(
            (85, y),
            line,
            font=subtitle_font,
            fill=(255, 255, 255)
        )
        y += 58

    # Kichik o'lchamga o'tkazish
    img = img.resize(
        (VIDEO_WIDTH, VIDEO_HEIGHT),
        Image.Resampling.LANCZOS
    )

    file_name = f"frame{number}.jpg"

    img.save(
        file_name,
        "JPEG",
        quality=85,
        optimize=True
    )

    return file_name


# ==========================================
# TEZKOR VIDEO
# ==========================================

def create_video(script):

    log("Ovoz fayli ochilmoqda...")

    audio = AudioFileClip(AUDIO_FILE)
    duration = audio.duration

    if duration <= 0:
        audio.close()
        raise ValueError("Ovoz davomiyligi noto'g'ri")

    text_parts = split_text(script)
    scene_duration = duration / 3

    clips = []
    video = None

    try:

        for i in range(3):

            log(f"{i+1}/3 kadr tayyorlanmoqda...")

            image_path = make_frame(
                i + 1,
                text_parts[i]
            )

            clip = ImageClip(image_path).set_duration(
                scene_duration
            )

            clips.append(clip)

        log("Kadrlar birlashtirilmoqda...")

        video = concatenate_videoclips(
            clips,
            method="chain"
        )

        video = video.set_audio(audio)

        log("MP4 video tezkor rejimda saqlanmoqda...")

        video.write_videofile(
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

        if video is not None:
            video.close()

        for clip in clips:
            try:
                clip.close()
            except Exception:
                pass

        audio.close()


# ==========================================
# YOUTUBE YUKLASH
# ==========================================

def upload_to_youtube(title):

    log("YouTube bilan bog'lanilmoqda...")

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

    request = youtube.videos().insert(
        part="snippet,status",

        body={
            "snippet": {
                "title": f"{title} | {VIDEO_PART}-qism #shorts",
                "description": (
                    "Sirli hikoyalar olamiga xush kelibsiz!\n"
                    "Davomini o'tkazib yubormang!\n"
                    "#shorts #uzbek #sirli #hikoya"
                ),
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
                f"YouTube yuklash: "
                f"{int(status.progress() * 100)}%"
            )

    log("YouTube video yuklandi: " + response["id"])


# ==========================================
# ASOSIY DASTUR
# ==========================================

def main():

    log("==============================")
    log("YOUTUBE SHORTS AVTOMATIK TIZIM")
    log("==============================")

    log(f"Video qismi: {VIDEO_PART}")

    log("1. Hikoya yaratilmoqda...")

    title, script = create_script()

    log("2. Ovoz yaratilmoqda...")

    asyncio.run(make_voice(script))

    log("3. Tezkor video yaratilmoqda...")

    create_video(script)

    log("4. YouTube ga yuklanmoqda...")

    upload_to_youtube(title)

    log("==============================")
    log("ISH MUVAFFAQIYATLI TUGADI!")
    log("==============================")


if __name__ == "__main__":
    main()
