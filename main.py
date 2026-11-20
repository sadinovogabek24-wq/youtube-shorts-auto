
import os
import re
import asyncio
import textwrap
import time
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


# SOZLAMALAR
API_KEY = os.environ.get("GEMINI_API_KEY")

MODEL = "gemini-3.8-flash"
BACKUP_MODEL = "gemini-3.5-flash-lite"

VOICE = "uz-UZ-SardorNeural"

W, H = 1080, 1920
FPS = 24

if not API_KEY:
    raise ValueError("GEMINI_API_KEY topilmadi!")

client = genai.Client(api_key=API_KEY)


# 1. HIKOYA YARATISH
def create_script():

    prompt = """
    O'zbek tilida juda qiziqarli sirli hikoya yoz.
    Mavzu: Sirlar, tarix, koinot yoki hayratlanarli faktlar.
    220-280 ta so'z bo'lsin.
    Ovozda o'qilganda 90-150 soniya davom etsin.
    Birinchi jumla juda qiziqarli bo'lsin.
    Sodda va ravon o'zbek tilida yoz.
    Oxirida tomoshabinga savol ber.
    Faqat hikoyaning o'zini yoz.
    """

    last_error = None

    for model in [MODEL, BACKUP_MODEL]:

        print("Gemini modeli:", model, flush=True)

        for attempt in range(3):

            try:

                response = client.models.generate_content(
                    model=model,
                    contents=prompt
                )

                if not response.text:
                    raise ValueError("Hikoya yaratilmadi!")

                return response.text.strip()

            except Exception as error:

                last_error = error

                print("Gemini xatosi:", error, flush=True)

                if any(code in str(error) for code in [
                    "429", "500", "502", "503", "504"
                ]):

                    wait = 10 * (attempt + 1)

                    print(wait, "soniya kutamiz", flush=True)
                    time.sleep(wait)

                else:
                    raise

    raise RuntimeError(str(last_error))


# 2. OVOZ YARATISH
async def create_voice(script):

    speech = edge_tts.Communicate(
        script,
        VOICE
    )

    await speech.save("voice.mp3")

    print("Ovoz tayyor!", flush=True)


# 3. OVOZ DAVOMIYLIGINI TEKSHIRISH
def check_audio():

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

    if duration < 90 or duration > 150:
        return False

    return True


# 4. VIDEO FONI
def create_background():

    img = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(img)

    for y in range(H):

        c = int(20 + 35 * y / H)

        draw.line(
            (0, y, W, y),
            fill=(8, 12, c)
        )

    draw.ellipse(
        (100, 250, 950, 1100),
        outline=(45, 65, 110),
        width=12
    )

    draw.ellipse(
        (250, 450, 850, 1050),
        outline=(65, 45, 110),
        width=8
    )

    img.save("background.png")

    print("Fon tayyor!", flush=True)


# 5. SUBTITRLAR
def make_subtitles(script, duration):

    font_path = (
        "/usr/share/fonts/truetype/dejavu/"
        "DejaVuSans-Bold.ttf"
    )

    font = ImageFont.truetype(
        font_path,
        54
    )

    words = script.split()

    if not words:
        raise ValueError("Hikoya bo'sh!")

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

        x = (W - (bbox[2] - bbox[0])) // 2

        y = (300 - (bbox[3] - bbox[1])) // 2

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
            ImageClip(np.array(img))
            .set_start(start)
            .set_duration(end - start)
            .set_position(("center", 1250))
        )

        clips.append(clip)

    return clips


# 6. VIDEO YARATISH
def create_video(script):

    audio = AudioFileClip("voice.mp3")

    background = None
    video = None
    subtitles = []

    try:

        duration = audio.duration

        if duration < 90 or duration > 150:

            raise ValueError(
                f"Ovoz {duration:.1f} soniya. "
                "90-150 soniya kerak."
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

        print("VIDEO RENDER BOSHLANDI!", flush=True)

        video.write_videofile(
            "shorts.mp4",
            fps=FPS,
            codec="libx264",
            audio_codec="aac",
            preset="ultrafast",
            threads=2,
            ffmpeg_params=["-crf", "28"],
            audio_bitrate="128k"
        )

        print("VIDEO TAYYOR!", flush=True)

    finally:

        if video:
            video.close()

        if background:
            background.close()

        for clip in subtitles:
            clip.close()

        audio.close()


# 7. YOUTUBE'GA YUKLASH
def upload_to_youtube():

    print("YouTube'ga ulanish...", flush=True)

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

                "title": "Sirli hikoya | Sirlar Olami #Shorts",

                "description": (
                    "Qiziqarli sirli hikoyalar va "
                    "hayratlanarli faktlar.\n"
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

                "categoryId": "27"
            },

            "status": {

                "privacyStatus": "public",

                "selfDeclaredMadeForKids": False
            }
        },

        media_body=media
    )

    result = None

    print("YouTube'ga yuklash boshlandi...", flush=True)

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

    print("VIDEO MUVAFFAQIYATLI YUKLANDI!", flush=True)

    print(
        "Video ID:",
        video_id,
        flush=True
    )

    print(
        "Video havolasi: https://www.youtube.com/watch?v="
        + video_id,
        flush=True
    )


# 8. ASOSIY ISH JARAYONI
def main():

    print("SHORTS AUTOMATION ISHGA TUSHDI!", flush=True)

    script = None

    for attempt in range(3):

        print(
            f"{attempt + 1}-urinish: Hikoya yaratilmoqda...",
            flush=True
        )

        script = create_script()

        print("Ovoz tayyorlanmoqda...", flush=True)

        asyncio.run(create_voice(script))

        if check_audio():
            break

        print(
            "Ovoz 90-150 soniya emas. "
            "Yangi hikoya yaratiladi.",
            flush=True
        )

    else:

        raise RuntimeError(
            "3 urinishda ham 90-150 soniyalik ovoz olinmadi."
        )

    print("Fon yaratilmoqda...", flush=True)

    create_background()

    print("Video tayyorlanmoqda...", flush=True)

    create_video(script)

    if not os.path.exists("shorts.mp4"):
        raise FileNotFoundError("shorts.mp4 topilmadi!")

    if os.path.getsize("shorts.mp4") == 0:
        raise ValueError("Video fayli bo'sh!")

    print("YouTube'ga yuklanmoqda...", flush=True)

    upload_to_youtube()

    print(
        "BARCHA ISHLAR MUVAFFAQIYATLI TUGADI!",
        flush=True
    )


if __name__ == "__main__":

    main()
