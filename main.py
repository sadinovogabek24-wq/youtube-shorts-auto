
import os
import json
import asyncio
import random
import re
from PIL import Image, ImageDraw
import edge_tts
from moviepy.editor import (
    ImageClip,
    AudioFileClip,
    concatenate_videoclips
)
from google import genai
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials

# ==============================
# SOZLAMALAR
# ==============================

API_KEY = os.environ["GEMINI_API_KEY"]

client = genai.Client(api_key=API_KEY)

VOICE = "uz-UZ-SardorNeural"
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
VIDEO_PART = int(os.getenv("VIDEO_PART", "1"))

# ==============================
# GEMINI 3.5 -> 3.8
# ==============================

def gemini_text(prompt):
    models = [
        "gemini-3.5-flash-lite",
        "gemini-3.8-flash"
    ]

    last_error = None

    for model in models:
        try:
            print("Model ishlayapti:", model)

            response = client.models.generate_content(
                model=model,
                contents=prompt
            )

            if response.text:
                print("Ishlagan model:", model)
                return response.text

        except Exception as error:
            last_error = error
            print(model, "ishlamadi:", error)

    raise RuntimeError(f"Ikkala model ham ishlamadi: {last_error}")

# ==============================
# HIKOYA YARATISH
# ==============================

def create_script():
    file_name = "episode.json"

    if VIDEO_PART == 1:
        prompt = """
        O'zbek tilida sirli, juda qiziqarli hikoya yoz.
        Hikoya ikki qismdan iborat bo'lsin.
        Har bir qism 100-380 ta so'z bo'lsin.
        Birinchi qism oxiri juda kuchli sir bilan tugasin.
        Ikkinchi qism birinchi qismning bevosita davomi bo'lsin.
        Natijani faqat JSON shaklida ber:
        {
          "title": "Hikoya nomi",
          "part1": "Birinchi qism",
          "part2": "Ikkinchi qism"
        }
        """

        raw = gemini_text(prompt)
        match = re.search(r"\{.*\}", raw, re.S)

        if not match:
            raise ValueError("Hikoya JSON shaklida kelmadi")

        story = json.loads(match.group())
        with open(file_name, "w", encoding="utf-8") as f:
            json.dump(story, f, ensure_ascii=False, indent=2)

        return story["title"], story["part1"]

    if not os.path.exists(file_name):
        raise FileNotFoundError(
            "episode.json topilmadi. Avval 1-qismni ishga tushiring."
        )

    with open(file_name, "r", encoding="utf-8") as f:
        story = json.load(f)

    return story["title"], story["part2"]

# ==============================
# OVOZ YARATISH
# ==============================

async def make_voice(text):
    communicate = edge_tts.Communicate(
        text=text,
        voice=VOICE,
        rate="-5%",
        volume="+0%"
    )
    await communicate.save("voice.mp3")

# ==============================
# UCHTA KADR YARATISH
# ==============================

def make_frame(number, title):
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
        y = random.randint(0, VIDEO_HEIGHT)
        r = random.randint(1, 3)
        draw.ellipse(
            (x-r, y-r, x+r, y+r),
            fill=(180, 190, 220)
        )

    # Oy
    draw.ellipse(
        (760, 180, 960, 380),
        fill=(220, 220, 190)
    )

    # Tog'lar
    draw.polygon(
        [(0, 1250), (300, 750), (600, 1250)],
        fill=(20, 30, 55)
    )

    draw.polygon(
        [(350, 1250), (750, 680), (1080, 1250)],
        fill=(25, 35, 65)
    )

    # Uy
    draw.rectangle(
        (250, 1050, 800, 1650),
        fill=(12, 15, 25)
    )

    draw.polygon(
        [(200, 1050), (525, 800), (850, 1050)],
        fill=(35, 20, 30)
    )

    # Derazalar
    for x in [350, 600]:
        draw.rectangle(
            (x, 1150, x+100, 1300),
            fill=(220, 150, 50)
        )

    # Kadr raqami
    draw.text(
        (70, 100),
        f"SAHNA {number}",
        fill=(255, 220, 150)
    )

    img.save(f"frame{number}.png")

# ==============================
# VIDEO YARATISH
# ==============================

def create_video():
    audio = AudioFileClip("voice.mp3")
    duration = audio.duration

    scenes = []

    for i in range(1, 4):
        make_frame(i, "")
        clip = (
            ImageClip(f"frame{i}.png")
            .set_duration(duration / 3)
            .resize(lambda t: 1 + 0.08 * t / (duration / 3))
        )
        scenes.append(clip)

    video = concatenate_videoclips(
        scenes,
        method="compose"
    )

    video = video.set_audio(audio)

    video.write_videofile(
        "video.mp4",
        fps=24,
        codec="libx264",
        audio_codec="aac",
        preset="ultrafast"
    )

    video.close()
    audio.close()

# ==============================
# YOUTUBE YUKLASH
# ==============================

def upload_to_youtube(title):
    credentials = Credentials(
        None,
        refresh_token=os.environ["YOUTUBE_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["YOUTUBE_CLIENT_ID"],
        client_secret=os.environ["YOUTUBE_CLIENT_SECRET"],
        scopes=["https://www.googleapis.com/auth/youtube.upload"]
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
                "title": f"{title} | {VIDEO_PART}-qism #shorts",
                "description": (
                    "Sirli hikoyalar olamiga xush kelibsiz!\n"
                    "#shorts #uzbek #sirli"
                ),
                "tags": ["uzbek", "sirli hikoya", "shorts"]
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False
            }
        },
        media_body=MediaFileUpload(
            "video.mp4",
            mimetype="video/mp4",
            resumable=True
        )
    )

    result = request.execute()
    print("YouTube video yuklandi:", result["id"])

# ==============================
# ASOSIY DASTUR
# ==============================

def main():
    print("1. Hikoya yaratilmoqda...")

    title, script = create_script()

    print("2. Ovoz yaratilmoqda...")
    asyncio.run(make_voice(script))

    print("3. Uchta kadrli video yaratilmoqda...")
    create_video()

    print("4. YouTube ga yuklanmoqda...")
    upload_to_youtube(title)

    print("HAMMASI TUGADI!")

if __name__ == "__main__":
    main()
