
import os
import re
import json
import asyncio
import textwrap
import random

from PIL import Image, ImageDraw, ImageFont

# ==========================================
# PILLOW / MOVIEPY MOSLIK TUZATISHI
# ==========================================

if not hasattr(Image, "ANTIALIAS"):
    if hasattr(Image, "Resampling"):
        Image.ANTIALIAS = Image.Resampling.LANCZOS
    else:
        Image.ANTIALIAS = Image.LANCZOS

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


# ==========================================
# SOZLAMALAR
# ==========================================

VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920

VOICE = "uz-UZ-SardorNeural"

VIDEO_PART = int(os.getenv("VIDEO_PART", "1"))

EPISODE_FILE = "episode.json"
AUDIO_FILE = "voice.mp3"
VIDEO_FILE = "video.mp4"

client = genai.Client(
    api_key=os.environ["GEMINI_API_KEY"]
)


# ==========================================
# GEMINI 3.5 -> 3.8 ZAXIRA
# ==========================================

def gemini_text(prompt):

    models = [
        "gemini-3.5-flash-lite",
        "gemini-3.8-flash"
    ]

    last_error = None

    for model_name in models:

        try:
            print("Gemini modeli ishga tushmoqda:", model_name)

            response = client.models.generate_content(
                model=model_name,
                contents=prompt
            )

            result = response.text

            if not result:
                raise ValueError("Gemini bo'sh javob berdi")

            print("Ishlagan model:", model_name)

            return result

        except Exception as error:

            last_error = error

            print(
                model_name,
                "ishlamadi:",
                str(error)
            )

            print("Zaxira model sinab ko'riladi...")

    raise RuntimeError(
        "Gemini modellarining ikkalasi ham ishlamadi: "
        + str(last_error)
    )


# ==========================================
# JSON HIKOYA YARATISH
# ==========================================

def extract_json(raw_text):

    cleaned = raw_text.strip()

    cleaned = re.sub(
        r"^```(?:json)?",
        "",
        cleaned
    )

    cleaned = re.sub(
        r"```$",
        "",
        cleaned.strip()
    )

    match = re.search(
        r"\{.*\}",
        cleaned,
        re.S
    )

    if not match:
        raise ValueError(
            "Gemini javobidan JSON topilmadi"
        )

    return json.loads(match.group())


def create_script():

    if VIDEO_PART == 1:

        prompt = """
        O'zbek tilida juda qiziqarli va sirli hikoya yoz.

        Hikoya ikki qismdan iborat bo'lsin.

        Birinchi qism:
        - 100 dan 380 tagacha so'z.
        - Tomoshabinni boshidan qiziqtirsin.
        - Sirli voqea bilan boshlangan bo'lsin.
        - Oxirida kuchli hayajonli tugash bo'lsin.

        Ikkinchi qism:
        - 100 dan 380 tagacha so'z.
        - Birinchi qismning bevosita davomi bo'lsin.
        - Sirning sababini ochib bersin.
        - Yakuni qiziqarli bo'lsin.

        Matn ravon, tabiiy o'zbek tilida bo'lsin.
        Ovoz chiqarib o'qishga mos bo'lsin.

        Faqat quyidagi JSON formatida javob ber:

        {
          "title": "Hikoya nomi",
          "part1": "Birinchi qism matni",
          "part2": "Ikkinchi qism matni"
        }
        """

        raw = gemini_text(prompt)

        story = extract_json(raw)

        if not all(
            key in story
            for key in ["title", "part1", "part2"]
        ):
            raise ValueError(
                "Hikoya JSON ma'lumotlari to'liq emas"
            )

        with open(
            EPISODE_FILE,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                story,
                file,
                ensure_ascii=False,
                indent=2
            )

        return story["title"], story["part1"]

    elif VIDEO_PART == 2:

        if not os.path.exists(EPISODE_FILE):

            raise FileNotFoundError(
                "episode.json topilmadi. "
                "Avval 1-qismni ishga tushiring."
            )

        with open(
            EPISODE_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            story = json.load(file)

        return story["title"], story["part2"]

    else:

        raise ValueError(
            "VIDEO_PART faqat 1 yoki 2 bo'lishi kerak"
        )


# ==========================================
# MATNNI 3 QISMGA BO'LISH
# ==========================================

def split_text(text):

    words = text.split()

    if not words:
        raise ValueError("Hikoya matni bo'sh")

    chunk_size = max(1, len(words) // 3)

    chunks = [
        words[:chunk_size],
        words[chunk_size:chunk_size * 2],
        words[chunk_size * 2:]
    ]

    return [
        " ".join(chunk)
        for chunk in chunks
        if chunk
    ]


# ==========================================
# O'ZBEKCHA ERKAK OVOZI
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

    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"
    ]

    for path in font_paths:

        if os.path.exists(path):

            return ImageFont.truetype(
                path,
                size
            )

    return ImageFont.load_default()


# ==========================================
# 3 TA KADR YARATISH
# ==========================================

def make_frame(number, subtitle):

    random.seed(number)

    img = Image.new(
        "RGB",
        (VIDEO_WIDTH, VIDEO_HEIGHT),
        (5, 8, 25)
    )

    draw = ImageDraw.Draw(img)

    # Yulduzlar

    for _ in range(180):

        x = random.randint(0, VIDEO_WIDTH)
        y = random.randint(0, 1250)

        radius = random.randint(1, 3)

        draw.ellipse(
            (
                x - radius,
                y - radius,
                x + radius,
                y + radius
            ),
            fill=(190, 195, 220)
        )

    # Oy

    draw.ellipse(
        (760, 170, 960, 370),
        fill=(225, 220, 180)
    )

    # Tog'lar

    draw.polygon(
        [
            (0, 1250),
            (280, 750),
            (600, 1250)
        ],
        fill=(18, 28, 55)
    )

    draw.polygon(
        [
            (350, 1250),
            (750, 680),
            (1080, 1250)
        ],
        fill=(25, 35, 65)
    )

    # Kadrga qarab manzara

    if number == 1:

        # Birinchi kadr: uzoqdagi sirli uy

        draw.rectangle(
            (250, 1050, 820, 1600),
            fill=(12, 15, 25)
        )

        draw.polygon(
            [
                (190, 1050),
                (530, 790),
                (880, 1050)
            ],
            fill=(45, 25, 35)
        )

    elif number == 2:

        # Ikkinchi kadr: qorong'i bino

        draw.rectangle(
            (150, 900, 900, 1600),
            fill=(15, 18, 30)
        )

        draw.polygon(
            [
                (100, 900),
                (520, 620),
                (950, 900)
            ],
            fill=(40, 25, 40)
        )

    else:

        # Uchinchi kadr: sirli eshik

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

    # Derazalar

    for x in [350, 620]:

        draw.rectangle(
            (x, 1150, x + 90, 1290),
            fill=(220, 150, 55)
        )

    # Kadr raqami

    title_font = get_font(48)

    draw.text(
        (65, 90),
        f"SAHNA {number}",
        font=title_font,
        fill=(255, 220, 150)
    )

    # Subtitr uchun qora fon

    draw.rounded_rectangle(
        (45, 1510, 1035, 1840),
        radius=30,
        fill=(0, 0, 0)
    )

    subtitle_font = get_font(43)

    lines = textwrap.wrap(
        subtitle,
        width=32
    )

    lines = lines[:5]

    y = 1570

    for line in lines:

        draw.text(
            (85, y),
            line,
            font=subtitle_font,
            fill=(255, 255, 255)
        )

        y += 58

    file_name = f"frame{number}.png"

    img.save(file_name)

    return file_name


# ==========================================
# VIDEO YARATISH
# ==========================================

def create_video(script):

    audio = AudioFileClip(AUDIO_FILE)

    duration = audio.duration

    if duration <= 0:

        audio.close()

        raise ValueError("Ovoz davomiyligi noto'g'ri")

    text_parts = split_text(script)

    while len(text_parts) < 3:
        text_parts.append("")

    scene_duration = duration / 3

    clips = []

    try:

        for i in range(3):

            print(
                f"{i + 1}-kadr tayyorlanmoqda..."
            )

            image_path = make_frame(
                i + 1,
                text_parts[i]
            )

            base_clip = (
                ImageClip(image_path)
                .set_duration(scene_duration)
            )

            # Sekin kamera yaqinlashishi

            zoom_clip = base_clip.resize(
                lambda t: 1.0 + 0.05 * (
                    t / max(scene_duration, 0.01)
                )
            )

            # Video o'lchamini doim 1080x1920 saqlash

            zoom_clip = zoom_clip.crop(
                x_center=VIDEO_WIDTH / 2,
                y_center=VIDEO_HEIGHT / 2,
                width=VIDEO_WIDTH,
                height=VIDEO_HEIGHT
            )

            clips.append(zoom_clip)

        video = concatenate_videoclips(
            clips,
            method="compose"
        )

        video = video.set_audio(audio)

        print("Video saqlanmoqda...")

        video.write_videofile(
            VIDEO_FILE,
            fps=24,
            codec="libx264",
            audio_codec="aac",
            preset="ultrafast",
            threads=2
        )

        video.close()

    finally:

        for clip in clips:

            try:
                clip.close()
            except Exception:
                pass

        audio.close()

    print("Video tayyor!")


# ==========================================
# YOUTUBE GA YUKLASH
# ==========================================

def upload_to_youtube(title):

    credentials = Credentials(
        None,
        refresh_token=os.environ[
            "YOUTUBE_REFRESH_TOKEN"
        ],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ[
            "YOUTUBE_CLIENT_ID"
        ],
        client_secret=os.environ[
            "YOUTUBE_CLIENT_SECRET"
        ],
        scopes=[
            "https://www.googleapis.com/auth/youtube.upload"
        ]
    )

    youtube = build(
        "youtube",
        "v3",
        credentials=credentials
    )

    request = youtube.videos().insert(
        part="snippet,status",

        body={
            "snippet": {
                "title": (
                    f"{title} | {VIDEO_PART}-qism #shorts"
                ),

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
            resumable=True
        )
    )

    result = request.execute()

    print(
        "YouTube video yuklandi:",
        result["id"]
    )


# ==========================================
# ASOSIY DASTUR
# ==========================================

def main():

    print("==============================")
    print("YOUTUBE SHORTS AVTOMATIK TIZIM")
    print("==============================")

    print("1. Hikoya yaratilmoqda...")

    title, script = create_script()

    print("2. Ovoz yaratilmoqda...")

    asyncio.run(
        make_voice(script)
    )

    print("3. Uchta kadrli video yaratilmoqda...")

    create_video(script)

    print("4. YouTube ga yuklanmoqda...")

    upload_to_youtube(title)

    print("==============================")
    print("ISH MUVAFFAQIYATLI TUGADI!")
    print("==============================")


if __name__ == "__main__":

    main()
