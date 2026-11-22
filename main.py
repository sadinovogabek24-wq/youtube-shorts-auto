
import os
import re
import json
import time
import base64
import asyncio
import requests
import edge_tts

from datetime import datetime, timedelta, timezone
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

from google import genai
from moviepy.editor import (
    VideoFileClip,
    AudioFileClip,
    ImageClip,
    CompositeVideoClip,
    CompositeAudioClip,
    concatenate_videoclips,
    vfx
)

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload


# =====================================
# SOZLAMALAR
# =====================================

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

YOUTUBE_CLIENT_ID = os.environ["YOUTUBE_CLIENT_ID"]
YOUTUBE_CLIENT_SECRET = os.environ["YOUTUBE_CLIENT_SECRET"]
YOUTUBE_REFRESH_TOKEN = os.environ["YOUTUBE_REFRESH_TOKEN"]

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPOSITORY = os.environ.get(
    "GITHUB_REPOSITORY",
    "sadinovogabek24-wq/youtube-shorts-auto"
)
GITHUB_BRANCH = os.environ.get("GITHUB_REF_NAME", "main")

TEXT_MODEL = "gemini-3.8-flash"
VIDEO_MODEL = "gemini-omni-1.2-flash"

VOICE = "uz-UZ-SardorNeural"

VIDEO_SIZE = (1080, 1920)
SCENE_COUNT = 4
SCENE_SECONDS = 10

client = genai.Client(api_key=GEMINI_API_KEY)


# =====================================
# GITHUB ORQALI HIKOYA SAQLASH
# =====================================

def github_headers():
    if not GITHUB_TOKEN:
        raise RuntimeError(
            "GITHUB_TOKEN yo'q. daily.yml fayliga token qo'shing."
        )

    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }


def github_get_file(path):
    url = (
        f"https://api.github.com/repos/"
        f"{GITHUB_REPOSITORY}/contents/{path}"
    )

    response = requests.get(
        url,
        headers=github_headers(),
        params={"ref": GITHUB_BRANCH},
        timeout=30
    )

    if response.status_code == 404:
        return None

    response.raise_for_status()

    data = response.json()
    return base64.b64decode(data["content"])


def github_save_file(path, content, message):
    url = (
        f"https://api.github.com/repos/"
        f"{GITHUB_REPOSITORY}/contents/{path}"
    )

    headers = github_headers()

    old = requests.get(
        url,
        headers=headers,
        params={"ref": GITHUB_BRANCH},
        timeout=30
    )

    payload = {
        "message": message,
        "content": base64.b64encode(content).decode("utf-8"),
        "branch": GITHUB_BRANCH
    }

    if old.status_code == 200:
        payload["sha"] = old.json()["sha"]
    elif old.status_code != 404:
        old.raise_for_status()

    response = requests.put(
        url,
        headers=headers,
        json=payload,
        timeout=60
    )

    response.raise_for_status()
    print("GitHub saqlandi:", path)


# =====================================
# QISMNI ANIQLASH
# =====================================

def get_part():
    manual = os.environ.get("SHORTS_PART")

    if manual in ("1", "2"):
        return int(manual)

    hour = datetime.now(timezone.utc).hour

    # 17:00 UTC = 22:00 Toshkent
    # 05:00 UTC = 10:00 Toshkent

    if hour >= 12:
        return 1

    return 2


def get_series_date(part):
    today = datetime.now(timezone.utc).date()

    if part == 1:
        return today

    return today - timedelta(days=1)


# =====================================
# YANGI HIKOYA YARATISH
# =====================================

TOPICS = [
    "Sirli ravishda g'oyib bo'layotgan shahar aholisi",
    "Okean tubida topilgan noma'lum ulkan inshoot",
    "Tashlandiq shahardagi sirli yerosti tunneli",
    "Hech kim kira olmaydigan qadimiy qal'a",
    "Har kecha bir xil vaqtda paydo bo'ladigan sirli odam",
    "O'rmonda topilgan noma'lum qadimiy eshik",
    "Taqiqlangan orolda sodir bo'lgan dahshatli voqealar",
    "O'yin ichidagi hech kim bilmagan yashirin xona",
    "Qadimiy afsonadagi maxluqning izlari",
    "Yo'qolgan ekspeditsiyaning so'nggi siri"
]


def create_story(series_date):
    index = series_date.toordinal() % len(TOPICS)
    topic = TOPICS[index]

    prompt = f"""
Sen professional sirli kino ssenariychisisan.

Mavzu: {topic}

O'zbek auditoriyasi uchun juda qiziqarli,
sirli, hayajonli va kinodek hikoya yarat.

Hikoya ikkita alohida YouTube Shorts qismidan iborat bo'lsin.

MUHIM TALABLAR:

1. Faqat odam personajlari ishlat.
2. Bir xil personajlar ikkala qismda ham qatnashsin.
3. Har bir personajning yoshi, yuzi, sochi,
   kiyimi va tashqi ko'rinishi aniq belgilansin.
4. Birinchi qism sirli vaziyat bilan boshlansin.
5. Birinchi qism oxirida dahshatli cliffhanger bo'lsin.
6. Ikkinchi qism birinchi qismdagi voqeani davom ettirsin.
7. Ikkinchi qismda boshqa katta yoshli odam
   yoki tergovchi sirni sezib, tekshirishni boshlasin.
8. Yakunda sirning yechimi ochilsin.
9. Har bir qismda aynan 4 ta sahna bo'lsin.
10. Har bir sahna taxminan 10 soniyaga mo'ljallansin.
11. Ovoz matni o'zbek tilida bo'lsin.
12. Video promptlari ingliz tilida yozilsin.
13. Har bir sahnada aniq harakat tasvirlansin.
14. Bitta sahnada bitta asosiy voqea ko'rsatilsin.
15. Personajlar sahnalar orasida o'zgarmasin.

JSON shaklida javob ber:

{{
  "title": "Hikoya nomi",
  "characters": "Barcha personajlarning batafsil tashqi ko'rinishi",
  "part1": {{
    "scenes": [
      {{
        "narration": "O'zbekcha ovoz matni",
        "visual": "English cinematic video prompt"
      }}
    ]
  }},
  "part2": {{
    "scenes": [
      {{
        "narration": "O'zbekcha ovoz matni",
        "visual": "English cinematic video prompt"
      }}
    ]
  }}
}}

Har bir qismda 4 ta sahna bo'lsin.
Har bir narration qisqa, ammo mazmunli bo'lsin.
"""


    response = client.models.generate_content(
        model=TEXT_MODEL,
        contents=prompt,
        config={
            "response_mime_type": "application/json"
        }
    )

    story = json.loads(response.text)

    for part in ("part1", "part2"):
        scenes = story[part]["scenes"]

        if len(scenes) != SCENE_COUNT:
            raise RuntimeError(
                f"{part}: 4 ta sahna yaratilmagan."
            )

    story["topic"] = topic
    story["series_date"] = str(series_date)

    return story


# =====================================
# HIKOYA HOLATINI SAQLASH
# =====================================

def load_or_create_story(part, series_date):

    if part == 1:
        story = create_story(series_date)

        github_save_file(
            "series_state.json",
            json.dumps(
                story,
                ensure_ascii=False,
                indent=2
            ).encode("utf-8"),
            "Yangi ikki qismli hikoya"
        )

        print("Yangi hikoya:", story["title"])
        return story

    data = github_get_file("series_state.json")

    if not data:
        raise RuntimeError(
            "1-qism hikoyasi topilmadi. "
            "Avval 1-qismni yaratish kerak."
        )

    story = json.loads(data)

    if story["series_date"] != str(series_date):
        raise RuntimeError(
            "Ikkinchi qism uchun sana mos kelmadi."
        )

    print("Davom ettirilayotgan hikoya:", story["title"])

    return story


# =====================================
# AI VIDEO YARATISH
# =====================================

def generate_ai_video(prompt, filename, reference=None):

    character_description = """
    Maintain exactly the same main human character:
    same face, same hairstyle, same clothing,
    same age and same body proportions.
    Cinematic realistic film quality.
    Natural human movement, realistic physics,
    detailed environment, dramatic lighting.
    Vertical 9:16 video.
    No random unrelated shots.
    No scene montage.
    No subtitles or text overlays.
    """

    full_prompt = (
        character_description
        + "\nScene action:\n"
        + prompt
    )

    inputs = []

    if reference and os.path.exists(reference):
        with open(reference, "rb") as f:
            image_data = base64.b64encode(
                f.read()
            ).decode("utf-8")

        inputs.append({
            "type": "image",
            "data": image_data,
            "mime_type": "image/png"
        })

    inputs.append({
        "type": "text",
        "text": full_prompt
    })

    print("AI video yaratilmoqda:", filename)

    interaction = client.interactions.create(
        model=VIDEO_MODEL,
        input=inputs,
        response_format={
            "type": "video",
            "aspect_ratio": "9:16",
            "duration": f"{SCENE_SECONDS}s"
        }
    )

    if not interaction.output_video:
        raise RuntimeError("AI video javobi bo'sh.")

    if not interaction.output_video.data:
        raise RuntimeError("Video ma'lumoti olinmadi.")

    video_data = base64.b64decode(
        interaction.output_video.data
    )

    with open(filename, "wb") as f:
        f.write(video_data)

    if os.path.getsize(filename) < 10000:
        raise RuntimeError("Video fayli juda kichik.")

    print("Video tayyor:", filename)

    return filename


# =====================================
# PERSONAJ RASMINI SAQLASH
# =====================================

def create_character_reference(video_path):

    clip = VideoFileClip(video_path)

    frame = clip.get_frame(
        min(1.0, clip.duration - 0.1)
    )

    image = Image.fromarray(frame).convert("RGB")
    image.save("character_reference.png")

    clip.close()

    github_save_file(
        "character_reference.png",
        open("character_reference.png", "rb").read(),
        "Hikoya bosh qahramoni reference rasmi"
    )

    print("Personaj rasmi saqlandi.")


# =====================================
# O'ZBEKCHA ERKAK OVOZI
# =====================================

def create_voice(text, filename):

    async def generate():
        communicate = edge_tts.Communicate(
            text=text,
            voice=VOICE,
            rate="-5%",
            pitch="-2Hz"
        )

        await communicate.save(filename)

    asyncio.run(generate())

    print("Ovoz tayyor:", filename)


# =====================================
# SUBTITR RASMI
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


def make_subtitle(text, filename):

    image = Image.new(
        "RGBA",
        VIDEO_SIZE,
        (0, 0, 0, 0)
    )

    draw = ImageDraw.Draw(image)
    font = get_font(43)

    words = text.split()
    lines = []
    current = ""

    for word in words:
        test = (current + " " + word).strip()

        if draw.textbbox((0, 0), test, font=font)[2] > 930:
            lines.append(current)
            current = word
        else:
            current = test

    if current:
        lines.append(current)

    lines = lines[:3]

    y = 0

    for line in lines:
        box = draw.textbbox((0, 0), line, font=font)
        width = box[2] - box[0]

        x = (1080 - width) // 2

        draw.text(
            (x + 2, 1460 + y + 3),
            line,
            font=font,
            fill=(0, 0, 0, 255)
        )

        draw.text(
            (x, 1460 + y),
            line,
            font=font,
            fill=(255, 255, 255, 255),
            stroke_width=2,
            stroke_fill=(0, 0, 0, 255)
        )

        y += 58

    image.save(filename)


# =====================================
# OXIRGI EKRAN
# =====================================

def make_outro(part, filename):

    image = Image.new(
        "RGBA",
        VIDEO_SIZE,
        (0, 0, 0, 0)
    )

    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle(
        (65, 1390, 1015, 1810),
        radius=45,
        fill=(0, 0, 0, 225)
    )

    title_font = get_font(65)
    button_font = get_font(35)

    if part == 1:

        text = "DAVOMI 2-QISMDA"

        box = draw.textbbox(
            (0, 0), text, font=title_font
        )

        x = (1080 - (box[2] - box[0])) // 2

        draw.text(
            (x, 1530),
            text,
            font=title_font,
            fill=(255, 220, 70, 255)
        )

        small = "Keyingi qismni o'tkazib yubormang!"

        box = draw.textbbox(
            (0, 0), small, font=button_font
        )

        x = (1080 - (box[2] - box[0])) // 2

        draw.text(
            (x, 1650),
            small,
            font=button_font,
            fill="white"
        )

    else:

        buttons = [
            (90, 1510, 365, 1690, "LIKE"),
            (400, 1510, 680, 1690, "IZOH"),
            (715, 1510, 990, 1690, "OBUNA")
        ]

        for x1, y1, x2, y2, label in buttons:

            color = (
                (215, 25, 32, 255)
                if label == "OBUNA"
                else (55, 55, 55, 255)
            )

            draw.rounded_rectangle(
                (x1, y1, x2, y2),
                radius=30,
                fill=color
            )

            box = draw.textbbox(
                (0, 0), label, font=button_font
            )

            tw = box[2] - box[0]
            th = box[3] - box[1]

            draw.text(
                (
                    x1 + (x2 - x1 - tw) // 2,
                    y1 + (y2 - y1 - th) // 2
                ),
                label,
                font=button_font,
                fill="white"
            )

        footer = "LAYK BOSING  •  FIKR YOZING  •  OBUNA BO'LING"

        draw.text(
            (100, 1740),
            footer,
            font=get_font(23),
            fill="white"
        )

    image.save(filename)


# =====================================
# VIDEO SAHNALARINI BIRLASHTIRISH
# =====================================

def create_video(story, part, reference):

    section = story[f"part{part}"]

    clips = []

    for i, scene in enumerate(section["scenes"]):

        video_file = f"scene_{i+1}.mp4"
        voice_file = f"voice_{i+1}.mp3"
        subtitle_file = f"subtitle_{i+1}.png"

        visual = (
            story["characters"]
            + "\n"
            + scene["visual"]
        )

        generate_ai_video(
            visual,
            video_file,
            reference
        )

        if part == 1 and i == 0:
            create_character_reference(video_file)
            reference = "character_reference.png"

        create_voice(
            scene["narration"],
            voice_file
        )

        make_subtitle(
            scene["narration"],
            subtitle_file
        )

        video = VideoFileClip(video_file).resize(
            newsize=VIDEO_SIZE
        )

        voice = AudioFileClip(voice_file)

        duration = max(video.duration, voice.duration)

        if voice.duration > video.duration:

            extra = voice.duration - video.duration

            video = video.fx(
                vfx.freeze,
                t=max(0, video.duration - 0.1),
                freeze_duration=extra
            )

        video = video.set_duration(duration)

        audio_layers = [voice.volumex(1.0)]

        if video.audio:
            audio_layers.append(
                video.audio.volumex(0.10)
            )

        combined_audio = CompositeAudioClip(
            audio_layers
        ).set_duration(duration)

        video = video.set_audio(combined_audio)

        subtitle = (
            ImageClip(
                subtitle_file,
                transparent=True
            )
            .set_duration(duration)
            .set_position(("center", "center"))
        )

        final_scene = CompositeVideoClip(
            [video, subtitle],
            size=VIDEO_SIZE
        )

        clips.append(final_scene)

        print(
            f"{i+1}/{SCENE_COUNT} sahna tayyor."
        )

    final = concatenate_videoclips(
        clips,
        method="compose"
    )

    # =================================
    # YAKUNIY OVOZ VA CTA
    # =================================

    if part == 1:
        ending_text = (
            "Bu sir hali tugamadi. "
            "Davomi ikkinchi qismda."
        )
    else:
        ending_text = (
            "Agar hikoya sizga yoqqan bo'lsa, "
            "layk bosing, izoh yozing va "
            "kanalga obuna bo'ling. "
            "Yangi sirli hikoyalarda ko'rishamiz!"
        )

    create_voice(
        ending_text,
        "ending.mp3"
    )

    make_outro(
        part,
        "outro.png"
    )

    ending_voice = AudioFileClip("ending.mp3")

    outro_duration = max(
        5,
        ending_voice.duration
    )

    last_frame = ImageClip(
        final.get_frame(final.duration - 0.05)
    ).set_duration(outro_duration)

    outro_image = (
        ImageClip("outro.png", transparent=True)
        .set_duration(outro_duration)
    )

    outro_video = CompositeVideoClip(
        [last_frame, outro_image],
        size=VIDEO_SIZE
    ).set_audio(ending_voice)

    final = concatenate_videoclips(
        [final, outro_video],
        method="compose"
    )

    final.write_videofile(
        "shorts.mp4",
        fps=24,
        codec="libx264",
        audio_codec="aac",
        preset="ultrafast",
        threads=2,
        bitrate="5000k"
    )

    for clip in clips:
        clip.close()

    final.close()

    print("YAKUNIY VIDEO TAYYOR!")

    return "shorts.mp4"


# =====================================
# YOUTUBE'GA YUKLASH
# =====================================

def upload_youtube(filename, story, part):

    credentials = Credentials(
        token=None,
        refresh_token=YOUTUBE_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=YOUTUBE_CLIENT_ID,
        client_secret=YOUTUBE_CLIENT_SECRET,
        scopes=[
            "https://www.googleapis.com/auth/youtube.upload"
        ]
    )

    youtube = build(
        "youtube",
        "v3",
        credentials=credentials
    )

    title = (
        story["title"]
        + f" | {part}-QISM #shorts"
    )

    description = f"""
{story['title']}

Bu sirli hikoyaning {part}-qismi.

{"Davomi ikkinchi qismda!" if part == 1 else "Yangi sirli hikoyalar uchun obuna bo'ling!"}

#shorts #sirlar #dahshat #afsona #uzbek
"""

    body = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "categoryId": "24",
            "tags": [
                "shorts",
                "sirli hikoyalar",
                "dahshat",
                "afsonalar",
                "uzbek"
            ]
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False
        }
    }

    media = MediaFileUpload(
        filename,
        mimetype="video/mp4",
        resumable=True
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
                f"Yuklanmoqda: {int(status.progress() * 100)}%"
            )

    print(
        "YOUTUBE VIDEO JOYLANDI:",
        response["id"]
    )


# =====================================
# ASOSIY DASTUR
# =====================================

def main():

    part = get_part()
    series_date = get_series_date(part)

    print("=" * 50)
    print("AI SIRLI SHORTS")
    print("QISM:", part)
    print("SANA:", series_date)
    print("=" * 50)

    story = load_or_create_story(
        part,
        series_date
    )

    reference = None

    if part == 2:

        reference_data = github_get_file(
            "character_reference.png"
        )

        if not reference_data:
            raise RuntimeError(
                "Bosh qahramon rasmi topilmadi."
            )

        with open(
            "character_reference.png",
            "wb"
        ) as f:
            f.write(reference_data)

        reference = "character_reference.png"

    video = create_video(
        story,
        part,
        reference
    )

    upload_youtube(
        video,
        story,
        part
    )

    print("=" * 50)
    print("BARCHA ISHLAR MUVAFFAQIYATLI TUGADI")
    print("=" * 50)


if __name__ == "__main__":
    main()
