
import os
import re
import time
import asyncio
import textwrap
import numpy as np

from PIL import Image, ImageDraw, ImageFont
from google import genai
import edge_tts

from moviepy.editor import (
    ImageClip,
    AudioFileClip,
    CompositeVideoClip
)

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request


# =====================================
# 1. SOZLAMALAR
# =====================================

API_KEY = os.environ.get("GEMINI_API_KEY")

MODEL = "gemini-3.5-flash-lite"

VOICE = "uz-UZ-SardorNeural"

W = 1080
H = 1920
FPS = 24

MIN_DURATION = 45
MAX_DURATION = 180

if not API_KEY:
    raise ValueError("GEMINI_API_KEY topilmadi!")

client = genai.Client(api_key=API_KEY)


# =====================================
# 2. GEMINI ORQALI HIKOYA YARATISH
# =====================================

def create_script():

    prompt = """
    O'zbek tilida juda qiziqarli sirli hikoya yoz.

    Mavzular:
    - Sirli voqealar
    - Tarixiy jumboqlar
    - Koinot sirlari
    - Hayratlanarli faktlar
    - Noma'lum hodisalar

    TALABLAR:

    1. 300-350 ta so'z yoz.
    2. Birinchi jumla juda qiziqarli bo'lsin.
    3. Tomoshabinni boshidan oxirigacha qiziqtir.
    4. Sodda va ravon o'zbek tilida yoz.
    5. Hikoyada qiziqarli burilish bo'lsin.
    6. Oxirida tomoshabinga savol ber.
    7. Faqat hikoyaning o'zini yoz.
    """

    for attempt in range(3):

        try:

            print(
                "Gemini hikoya yaratmoqda...",
                flush=True
            )

            response = client.models.generate_content(
                model=MODEL,
                contents=prompt
            )

            if not response.text:
                raise ValueError(
                    "Gemini bo'sh javob qaytardi!"
                )

            script = response.text.strip()

            word_count = len(script.split())

            print(
                "Hikoya tayyor:",
                word_count,
                "ta so'z",
                flush=True
            )

            if word_count < 100:
                raise ValueError(
                    "Hikoya juda qisqa!"
                )

            return script

        except Exception as error:

            print(
                "Gemini xatosi:",
                str(error),
                flush=True
            )

            if attempt < 2 and any(
                code in str(error)
                for code in [
                    "429", "500", "502", "503", "504"
                ]
            ):

                print(
                    "15 soniya kutamiz...",
                    flush=True
                )

                time.sleep(15)

            else:
                raise

    raise RuntimeError(
        "Gemini hikoya yarata olmadi!"
    )


# =====================================
# 3. O'ZBEKCHA OVOZ YARATISH
# =====================================

async def create_voice(script):

    print(
        "Ovoz yaratilmoqda...",
        flush=True
    )

    communicate = edge_tts.Communicate(
        script,
        VOICE
    )

    await communicate.save("voice.mp3")

    if not os.path.exists("voice.mp3"):
        raise FileNotFoundError(
            "Ovoz fayli yaratilmagan!"
        )

    print(
        "Ovoz tayyor!",
        flush=True
    )


# =====================================
# 4. OVOZ DAVOMIYLIGINI ANIQLASH
# =====================================

def get_audio_duration():

    audio = AudioFileClip("voice.mp3")

    try:
        duration = audio.duration
    finally:
        audio.close()

    print(
        "Ovoz davomiyligi:",
        round(duration, 1),
        "soniya",
        flush=True
    )

    return duration


# =====================================
# 5. VIDEO FONINI YARATISH
# =====================================

def create_background():

    print(
        "Video foni yaratilmoqda...",
        flush=True
    )

    img = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(img)

    for y in range(H):

        ratio = y / H

        r = int(5 + ratio * 10)
        g = int(8 + ratio * 12)
        b = int(25 + ratio * 45)

        draw.line(
            (0, y, W, y),
            fill=(r, g, b)
        )

    draw.ellipse(
        (100, 250, 980, 1130),
        outline=(45, 65, 120),
        width=12
    )

    draw.ellipse(
        (240, 420, 840, 1020),
        outline=(65, 45, 120),
        width=8
    )

    img.save("background.png")

    print(
        "Fon tayyor!",
        flush=True
    )


# =====================================
# 6. SUBTITRLAR YARATISH
# =====================================

def make_subtitles(script, duration):

    font_path = (
        "/usr/share/fonts/truetype/dejavu/"
        "DejaVuSans-Bold.ttf"
    )

    if os.path.exists(font_path):

        font = ImageFont.truetype(
            font_path,
            54
        )

    else:

        font = ImageFont.load_default()

    words = script.split()

    if not words:
        raise ValueError(
            "Subtitr uchun matn yo'q!"
        )

    groups = [
        words[i:i + 7]
        for i in range(0, len(words), 7)
    ]

    clips = []

    total_words = len(words)
    current = 0

    for group in groups:

        start = duration * current / total_words

        current += len(group)

        end = duration * current / total_words

        img = Image.new(
            "RGBA",
            (W, 300),
            (0, 0, 0, 0)
        )

        draw = ImageDraw.Draw(img)

        text = "\n".join(
            textwrap.wrap(
                " ".join(group),
                width=27
            )
        )

        bbox = draw.multiline_textbbox(
            (0, 0),
            text,
            font=font,
            spacing=18,
            align="center",
            stroke_width=2
        )

        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        x = (W - text_width) // 2
        y = (300 - text_height) // 2

        draw.multiline_text(
            (x, y),
            text,
            font=font,
            fill="white",
            align="center",
            spacing=18,
            stroke_width=3,
            stroke_fill="black"
        )

        clip = (
            ImageClip(
                np.array(img),
                transparent=True
            )
            .set_start(start)
            .set_duration(end - start)
            .set_position(("center", 1250))
        )

        clips.append(clip)

    return clips


# =====================================
# 7. VIDEO YARATISH
# =====================================

def create_video(script):

    print(
        "Video tayyorlanmoqda...",
        flush=True
    )

    audio = AudioFileClip("voice.mp3")

    background = None
    video = None
    subtitles = []

    try:

        duration = audio.duration

        if duration < MIN_DURATION or duration > MAX_DURATION:

            raise ValueError(
                f"Ovoz davomiyligi noto'g'ri: {duration:.1f}"
            )

        background = (
            ImageClip("background.png")
            .set_duration(duration)
        )

        subtitles = make_subtitles(
            script,
            duration
        )

        video = (
            CompositeVideoClip(
                [background] + subtitles,
                size=(W, H)
            )
            .set_audio(audio)
        )

        print(
            "VIDEO RENDER BOSHLANDI!",
            flush=True
        )

        video.write_videofile(
            "shorts.mp4",
            fps=FPS,
            codec="libx264",
            audio_codec="aac",
            preset="ultrafast",
            threads=2,
            audio_fps=44100,
            audio_bitrate="128k",
            ffmpeg_params=[
                "-crf", "28",
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart"
            ]
        )

        print(
            "VIDEO TAYYOR!",
            flush=True
        )

    finally:

        if video:
            video.close()

        if background:
            background.close()

        for clip in subtitles:
            clip.close()

        audio.close()


# =====================================
# 8. YOUTUBE'GA YUKLASH
# =====================================

def upload_to_youtube():

    print(
        "YouTube'ga ulanish...",
        flush=True
    )

    required = [
        "YOUTUBE_REFRESH_TOKEN",
        "YOUTUBE_CLIENT_ID",
        "YOUTUBE_CLIENT_SECRET"
    ]

    for name in required:

        if not os.environ.get(name):

            raise ValueError(
                name + " GitHub Secrets'da topilmadi!"
            )

    credentials = Credentials(
        token=None,

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

    credentials.refresh(Request())

    youtube = build(
        "youtube",
        "v3",
        credentials=credentials,
        cache_discovery=False
    )

    media = MediaFileUpload(
        "shorts.mp4",
        mimetype="video/mp4",
        resumable=True,
        chunksize=8 * 1024 * 1024
    )

    request = youtube.videos().insert(

        part="snippet,status",

        body={

            "snippet": {

                "title": (
                    "Sirli hikoya | Sirlar Olami #Shorts"
                ),

                "description": (
                    "Qiziqarli sirli hikoyalar va "
                    "hayratlanarli faktlar.\n\n"
                    "Kanalga obuna bo'ling!\n"
                    "#Shorts #Uzbek #SirliHikoyalar"
                ),

                "tags": [
                    "sirlar",
                    "sirli hikoyalar",
                    "uzbek",
                    "shorts",
                    "tarix",
                    "koinot"
                ],

                "categoryId": "24"
            },

            "status": {

                "privacyStatus": "public",

                "selfDeclaredMadeForKids": False
            }
        },

        media_body=media
    )

    result = None

    print(
        "YouTube'ga yuklash boshlandi...",
        flush=True
    )

    while result is None:

        status, result = request.next_chunk()

        if status:

            print(
                "Yuklandi:",
                int(status.progress() * 100),
                "%",
                flush=True
            )

    video_id = result["id"]

    print(
        "VIDEO MUVAFFAQIYATLI YUKLANDI!",
        flush=True
    )

    print(
        "VIDEO HAVOLASI:",
        "https://www.youtube.com/watch?v=" + video_id,
        flush=True
    )


# =====================================
# 9. ASOSIY DASTUR
# =====================================

def main():

    print(
        "SHORTS AUTOMATION ISHGA TUSHDI!",
        flush=True
    )

    script = None
    audio_ready = False

    for attempt in range(3):

        print(
            f"{attempt + 1}-urinish: Hikoya yaratilmoqda...",
            flush=True
        )

        script = create_script()

        asyncio.run(
            create_voice(script)
        )

        duration = get_audio_duration()

        if MIN_DURATION <= duration <= MAX_DURATION:

            audio_ready = True

            print(
                "Ovoz qabul qilindi!",
                flush=True
            )

            break

        print(
            "Ovoz davomiyligi mos emas. "
            "Yangi hikoya yaratiladi.",
            flush=True
        )

    if not audio_ready:

        raise RuntimeError(
            "3 urinishda ham mos ovoz yaratilmadi!"
        )

    create_background()

    create_video(script)

    if not os.path.exists("shorts.mp4"):

        raise FileNotFoundError(
            "shorts.mp4 topilmadi!"
        )

    file_size = os.path.getsize("shorts.mp4")

    if file_size == 0:

        raise ValueError(
            "Video fayli bo'sh!"
        )

    print(
        "Video hajmi:",
        round(file_size / 1024 / 1024, 2),
        "MB",
        flush=True
    )

    upload_to_youtube()

    print(
        "BARCHA ISHLAR MUVAFFAQIYATLI TUGADI!",
        flush=True
    )


if __name__ == "__main__":

    main()
