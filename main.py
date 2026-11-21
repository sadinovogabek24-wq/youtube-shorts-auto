
import os
import re
import json
import math
import random
import asyncio
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
import edge_tts

from google import genai
from moviepy.editor import AudioFileClip, VideoClip


# =====================================
# SOZLAMALAR
# =====================================

W = 1080
H = 1920
FPS = 24

VOICE = "uz-UZ-SardorNeural"
OUTPUT = "shorts.mp4"

MIN_WORDS = 100
MAX_WORDS = 380
MAX_SECONDS = 180


# =====================================
# HIKOYA YARATISH
# =====================================

def create_episode():

    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise RuntimeError("GEMINI_API_KEY topilmadi")

    client = genai.Client(api_key=api_key)

    prompt = """
Sen professional o'zbek serial ssenariynavissisan.

YO'QOLGANLAR SIRI nomli sirli serial yarat.

BOSH QAHRAMON:
15 yoshli Jasur.

VOQEA:
Kichik shaharchada odamlar sirli ravishda yo'qolmoqda.
Jasur bu voqealarning sababini aniqlashga kirishadi.

1-QISM:
- Jasur izlanishni boshlaydi.
- Qora mashina va eski uyga duch keladi.
- Sirli belgilarni topadi.
- Oxirida kuchli hayajonli voqea yuz beradi.
- Sirning javobi ochilmasin.

2-QISM:
- Birinchi qism tugagan joydan davom etsin.
- Jasur izlanishni davom ettirsin.
- Yo'qolgan odamlarning taqdiri aniqlansin.
- Barcha asosiy sirlar ochilsin.
- Hikoya yakunlansin.

MUHIM QOIDALAR:
- Har bir qism 100 dan 380 tagacha so'z bo'lsin.
- Ikki qism bir-biriga uzviy bog'lansin.
- Jasurning xarakteri o'zgarmasin.
- O'zbek tilida yoz.
- Erkak ovozida o'qishga mos bo'lsin.
- Hikoya qiziqarli va hayajonli bo'lsin.
- Hikoya to'liq badiiy to'qima bo'lsin.

Faqat quyidagi JSON formatda javob ber:

{
  "title": "Yo'qolganlar siri",
  "part1": "Birinchi qism matni",
  "part2": "Ikkinchi qism matni"
}
"""

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )

    raw = (response.text or "").strip()

    raw = re.sub(
        r"^```(?:json)?\s*|\s*```$",
        "",
        raw,
        flags=re.I
    )

    match = re.search(r"\{.*\}", raw, flags=re.S)

    if not match:
        raise ValueError("Gemini JSON qaytarmadi")

    episode = json.loads(match.group(0))

    for key in ("part1", "part2"):

        story = episode.get(key, "").strip()

        if not story:
            raise ValueError(f"{key} bo'sh")

        word_count = len(story.split())

        print(f"{key}: {word_count} ta so'z")

        if not MIN_WORDS <= word_count <= MAX_WORDS:
            raise ValueError(
                f"{key} so'z soni noto'g'ri: {word_count}. "
                "100-380 ta so'z bo'lishi kerak."
            )

    return episode


# =====================================
# O'ZBEKCHA ERKAK OVOZI
# =====================================

async def make_voice(text):

    communicate = edge_tts.Communicate(
        text=text,
        voice=VOICE,
        rate="-5%",
        volume="+0%"
    )

    await communicate.save("voice.mp3")


def create_voice(text):

    asyncio.run(make_voice(text))


# =====================================
# SAHNA RANGLARI
# =====================================

PALETTES = [
    ((8, 15, 38), (34, 75, 115), (235, 160, 75)),
    ((28, 12, 48), (92, 42, 105), (255, 190, 95)),
    ((5, 34, 48), (20, 105, 110), (245, 205, 115)),
    ((35, 17, 18), (125, 55, 45), (255, 180, 95)),
    ((10, 20, 45), (48, 65, 125), (180, 210, 255)),
    ((25, 20, 12), (105, 82, 48), (255, 215, 125))
]


# =====================================
# RASM SAHNASI
# =====================================

def make_scene(seed, index):

    rng = random.Random(seed + index * 7919)

    top, bottom, glow = PALETTES[
        index % len(PALETTES)
    ]

    grad = np.zeros((H, W, 3), dtype=np.uint8)

    for channel in range(3):

        values = np.linspace(
            top[channel],
            bottom[channel],
            H,
            dtype=np.uint8
        )

        grad[:, :, channel] = values[:, None]

    img = Image.fromarray(grad, mode="RGB").convert("RGBA")

    draw = ImageDraw.Draw(img, "RGBA")

    # Yorug'lik
    gx = rng.randint(250, 830)
    gy = rng.randint(330, 780)

    for radius in range(400, 20, -20):

        alpha = max(
            2,
            int((400 - radius) * 0.12)
        )

        draw.ellipse(
            (
                gx-radius,
                gy-radius,
                gx+radius,
                gy+radius
            ),
            fill=(*glow, alpha)
        )

    # Yulduzlar
    for _ in range(150):

        x = rng.randint(0, W)
        y = rng.randint(0, 1200)
        r = rng.randint(1, 4)

        draw.ellipse(
            (x-r, y-r, x+r, y+r),
            fill=(255, 245, 220, 170)
        )

    # Oy
    r = rng.randint(80, 130)
    mx = rng.randint(250, 850)
    my = rng.randint(350, 750)

    draw.ellipse(
        (mx-r, my-r, mx+r, my+r),
        fill=(*glow, 220)
    )

    # Tog'lar
    for layer, base_y in enumerate(
        [1180, 1370, 1570]
    ):

        points = [(0, H)]
        x = 0

        while x <= W:

            y = base_y + rng.randint(-150, 150)

            points.append((x, y))
            x += rng.randint(90, 180)

        points.append((W, H))

        shade = max(0, 35 - layer * 8)

        draw.polygon(
            points,
            fill=(
                shade + 5,
                shade + 18,
                shade + 35,
                255
            )
        )

    # Qorong'i binolar
    ground = 1650

    draw.rectangle(
        (0, ground, W, H),
        fill=(5, 8, 15, 255)
    )

    for x in range(-30, W + 80, 130):

        bw = rng.randint(55, 125)
        bh = rng.randint(130, 420)

        draw.rectangle(
            (x, ground-bh, x+bw, ground),
            fill=(4, 7, 13, 255)
        )

        if rng.random() > 0.35:

            draw.polygon(
                [
                    (x-12, ground-bh),
                    (x+bw//2, ground-bh-65),
                    (x+bw+12, ground-bh)
                ],
                fill=(5, 8, 15, 255)
            )

    return img.convert("RGB")


# =====================================
# MATNNI SAHNALARGA BO'LISH
# =====================================

def split_into_scenes(text, count=8):

    sentences = re.split(
        r'(?<=[.!?])\s+',
        text.strip()
    )

    sentences = [
        s.strip()
        for s in sentences
        if s.strip()
    ]

    if not sentences:
        return [text]

    chunk_size = max(
        1,
        math.ceil(len(sentences) / count)
    )

    scenes = []

    for i in range(0, len(sentences), chunk_size):

        scenes.append(
            " ".join(sentences[i:i + chunk_size])
        )

    return scenes


# =====================================
# SHRIFT
# =====================================

def get_font(size):

    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"
    ]

    for path in paths:

        if os.path.exists(path):
            return ImageFont.truetype(path, size)

    return ImageFont.load_default()


# =====================================
# SUBTITR
# =====================================

def add_subtitle(img, text):

    draw = ImageDraw.Draw(img)
    font = get_font(46)

    words = text.split()

    lines = []
    current = ""

    for word in words:

        test = (current + " " + word).strip()

        bbox = draw.textbbox(
            (0, 0),
            test,
            font=font
        )

        if bbox[2] < 930:
            current = test

        else:

            if current:
                lines.append(current)

            current = word

    if current:
        lines.append(current)

    lines = lines[:4]

    y = 1430

    for line in lines:

        bbox = draw.textbbox(
            (0, 0),
            line,
            font=font
        )

        width = bbox[2] - bbox[0]
        x = (W - width) // 2

        draw.text(
            (x+3, y+3),
            line,
            font=font,
            fill=(0, 0, 0)
        )

        draw.text(
            (x, y),
            line,
            font=font,
            fill=(255, 255, 255)
        )

        y += 65

    return img


# =====================================
# HARAKATLI KADR
# =====================================

def make_frame(t, duration, scenes, scene_texts):

    scene_duration = duration / len(scenes)

    index = min(
        int(t / scene_duration),
        len(scenes) - 1
    )

    local_t = (
        t - index * scene_duration
    ) / scene_duration

    img = scenes[index].copy()

    # Kamera yaqinlashishi
    zoom = 1.0 + 0.10 * local_t

    new_w = int(W / zoom)
    new_h = int(H / zoom)

    left = int(
        (W - new_w) * local_t * 0.35
    )

    top = int(
        (H - new_h) * local_t * 0.35
    )

    left = max(0, min(left, W-new_w))
    top = max(0, min(top, H-new_h))

    img = img.crop(
        (
            left,
            top,
            left + new_w,
            top + new_h
        )
    )

    img = img.resize(
        (W, H),
        Image.Resampling.LANCZOS
    )

    img = add_subtitle(
        img,
        scene_texts[index]
    )

    return np.array(img)


# =====================================
# VIDEO YARATISH
# =====================================

def create_video(story, part):

    print("Ovoz tayyorlanmoqda...")

    create_voice(story)

    audio = AudioFileClip("voice.mp3")

    try:

        duration = audio.duration

        print(
            f"Ovoz davomiyligi: {duration:.1f} soniya"
        )

        if duration <= 0 or duration > MAX_SECONDS:

            raise ValueError(
                "Ovoz 180 soniyadan oshdi. "
                "Hikoyani qisqartirish kerak."
            )

        scene_texts = split_into_scenes(
            story,
            8
        )

        scenes = [
            make_scene(part * 1000, i)
            for i in range(len(scene_texts))
        ]

        def frame_function(t):

            return make_frame(
                t,
                duration,
                scenes,
                scene_texts
            )

        video = VideoClip(
            frame_function,
            duration=duration
        )

        video = video.set_audio(audio)

        print("Video tayyorlanmoqda...")

        video.write_videofile(
            OUTPUT,
            fps=FPS,
            codec="libx264",
            audio_codec="aac",
            preset="ultrafast",
            threads=2,
            bitrate="5000k"
        )

        video.close()

        print("Video yaratildi!")

    finally:

        audio.close()


# =====================================
# YOUTUBE'GA YUKLASH
# =====================================

def upload_to_youtube(
    video_file,
    title,
    description
):

    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    client_id = os.getenv("YOUTUBE_CLIENT_ID")
    client_secret = os.getenv("YOUTUBE_CLIENT_SECRET")
    refresh_token = os.getenv("YOUTUBE_REFRESH_TOKEN")

    if not all([
        client_id,
        client_secret,
        refresh_token
    ]):

        raise RuntimeError(
            "YouTube API ma'lumotlari topilmadi"
        )

    credentials = Credentials(
        None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=[
            "https://www.googleapis.com/auth/youtube.upload"
        ]
    )

    credentials.refresh(Request())

    youtube = build(
        "youtube",
        "v3",
        credentials=credentials
    )

    body = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "tags": [
                "uzbek",
                "hikoya",
                "sirli hikoya",
                "shorts",
                "serial"
            ],
            "categoryId": "22"
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False
        }
    }

    media = MediaFileUpload(
        video_file,
        mimetype="video/mp4",
        resumable=True
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media
    )

    response = request.execute()

    print(
        "YouTube video ID:",
        response.get("id")
    )


# =====================================
# ASOSIY DASTUR
# =====================================

def main():

    part = int(
        os.getenv("VIDEO_PART", "1")
    )

    if part not in (1, 2):

        raise ValueError(
            "VIDEO_PART 1 yoki 2 bo'lishi kerak"
        )

    episode_file = Path("episode.json")

    if part == 1:

        print("Yangi hikoya yaratilmoqda...")

        episode = create_episode()

        episode_file.write_text(
            json.dumps(
                episode,
                ensure_ascii=False,
                indent=2
            ),
            encoding="utf-8"
        )

    else:

        print("Birinchi qismdagi hikoya olinmoqda...")

        if not episode_file.exists():

            raise FileNotFoundError(
                "episode.json topilmadi. "
                "Avval 1-qism ishlashi kerak."
            )

        episode = json.loads(
            episode_file.read_text(
                encoding="utf-8"
            )
        )

    story = episode[f"part{part}"]

    print(
        f"{part}-qism tayyorlanmoqda..."
    )

    create_video(
        story,
        part
    )

    title = (
        f"YO'QOLGANLAR SIRI | {part}-QISM"
    )

    description = (
        f"YO'QOLGANLAR SIRI seriali — {part}-qism.\n"
        "Davomini o'tkazib yubormang!\n"
        "#uzbek #hikoya #shorts"
    )

    upload_to_youtube(
        OUTPUT,
        title,
        description
    )

    print("Barcha ishlar tugadi!")


if __name__ == "__main__":
    main()
