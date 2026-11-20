
import os
import re
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


# SOZLAMALAR
API_KEY = os.environ.get("GEMINI_API_KEY")
MODEL = "gemini-3.8-flash"
VOICE = "uz-UZ-SardorNeural"

W, H = 1080, 1920

if not API_KEY:
    raise ValueError("GEMINI_API_KEY topilmadi!")

client = genai.Client(api_key=API_KEY)


# 1. HIKOYA YARATISH
def create_script():
    prompt = """
    O'zbek tilida juda qiziqarli sirli hikoya yoz.
    Mavzu: Sirlar, tarix, koinot yoki hayratlanarli faktlar.
    250-330 ta so'z bo'lsin.
    Ovozda o'qilganda 90-150 soniya davom etsin.
    Dastlabki jumla tomoshabinni darhol qiziqtirsin.
    Sodda va ravon o'zbek tilida yoz.
    Oxirida tomoshabinga savol ber.
    Faqat hikoyaning o'zini yoz.
    """

    response = client.models.generate_content(
        model=MODEL,
        contents=prompt
    )

    if not response.text:
        raise ValueError("Gemini matn yaratmadi!")

    return response.text.strip()


# 2. O'ZBEKCHA OVOZ
async def create_voice(script):
    speech = edge_tts.Communicate(
        script,
        VOICE
    )

    await speech.save("voice.mp3")


# 3. VIDEO FONI
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


# 4. SUBTITRLAR
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
            .set_duration(max(0.1, end - start))
            .set_position(("center", 1250))
        )

        clips.append(clip)

    return clips


# 5. VIDEO YARATISH
def create_video(script):
    audio = AudioFileClip("voice.mp3")

    try:
        duration = audio.duration

        if duration < 90 or duration > 150:
            raise ValueError(
                f"Ovoz {duration:.1f} soniya. "
                "90-150 soniya oralig'ida bo'lishi kerak."
            )

        background = (
            ImageClip("background.png")
            .set_duration(duration)
            .resize(
                lambda t: 1 + 0.04 * t / duration
            )
            .crop(
                x_center=W / 2,
                y_center=H / 2,
                width=W,
                height=H
            )
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

        try:
            video.write_videofile(
                "shorts.mp4",
                fps=24,
                codec="libx264",
                audio_codec="aac",
                preset="ultrafast",
                threads=2
            )
        finally:
            video.close()

    finally:
        audio.close()


# 6. YOUTUBE'GA YUKLASH
def upload_to_youtube():
    print("YouTube'ga ulanish...")

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

    request = youtube.videos().insert(
        part="snippet,status",
        body={
            "snippet": {
                "title": "Sirli hikoya | Sirlar Olami",
                "description": (
                    "Qiziqarli sirli hikoyalar va "
                    "hayratlanarli faktlar.\n"
                    "Kanalga obuna bo'ling!"
                ),
                "tags": [
                    "sirlar",
                    "sirli hikoyalar",
                    "uzbek",
                    "shorts"
                ],
                "categoryId": "27"
            },
            "status": {
                "privacyStatus": "unlisted"
            }
        },
        media_body=MediaFileUpload(
            "shorts.mp4",
            mimetype="video/mp4",
            resumable=True
        )
    )

    result = request.execute()

    print(
        "YUKLANDI! Video ID:",
        result["id"]
    )

    print(
        "Video havolasi: https://www.youtube.com/watch?v="
        + result["id"]
    )


# 7. ASOSIY ISH JARAYONI
def main():
    print("1. Hikoya yaratilmoqda...")
    script = create_script()

    print("2. Ovoz tayyorlanmoqda...")
    asyncio.run(create_voice(script))

    print("3. Fon yaratilmoqda...")
    create_background()

    print("4. Video tayyorlanmoqda...")
    create_video(script)

    print("5. YouTube'ga yuklanmoqda...")
    upload_to_youtube()

    print("BARCHA ISHLAR TUGADI!")


if __name__ == "__main__":
    main()
