
import os
import asyncio
import textwrap
from PIL import Image, ImageDraw, ImageFont
from google import genai
import edge_tts
from moviepy.editor import ImageClip, AudioFileClip

API_KEY = os.environ.get("GEMINI_API_KEY")

if not API_KEY:
    raise ValueError("GEMINI_API_KEY topilmadi!")

client = genai.Client(api_key=API_KEY)

VOICE = "uz-UZ-SardorNeural"
MODEL = "gemini-3.8-flash"

def create_script():
    prompt = """
    O'zbek tilida qiziqarli YouTube Shorts uchun
    40-50 soniyalik matn yoz.
    Mavzu: Sirli va hayratlanarli fakt.
    Boshlanishi odamni qiziqtirsin.
    Oxirida tomoshabinga savol ber.
    Faqat o'zbekcha matn yoz.
    Sarlavha va izohlarni qo'shma.
    """
    response = client.models.generate_content(
        model=MODEL,
        contents=prompt
    )
    if not response.text:
        raise ValueError("Gemini matn yaratmadi!")
    return response.text.strip()

def create_image(title):
    width, height = 1080, 1920
    img = Image.new("RGB", (width, height), (15, 20, 45))
    draw = ImageDraw.Draw(img)

    for y in range(height):
        color = (
            15,
            20 + int(y / height * 20),
            45 + int(y / height * 35)
        )
        draw.line((0, y, width, y), fill=color)

    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    font = ImageFont.truetype(font_path, 68)

    lines = textwrap.wrap(title, width=20)
    text = "\n".join(lines[:5])

    draw.multiline_text(
        (70, 650),
        text,
        font=font,
        fill="white",
        spacing=35,
        align="center"
    )

    img.save("background.png")

async def create_voice(script):
    communicate = edge_tts.Communicate(
        script,
        VOICE
    )
    await communicate.save("voice.mp3")

def create_video():
    audio = AudioFileClip("voice.mp3")
    duration = min(audio.duration, 58)

    image = ImageClip("background.png").set_duration(duration)
    image = image.set_audio(audio.subclip(0, duration))

    image.write_videofile(
        "shorts.mp4",
        fps=24,
        codec="libx264",
        audio_codec="aac"
    )

    audio.close()
    image.close()

def main():
    print("Matn yaratilmoqda...")
    script = create_script()

    print("Ovoz tayyorlanmoqda...")
    asyncio.run(create_voice(script))

    print("Rasm tayyorlanmoqda...")
    create_image("SIRLI FAKTLAR")

    print("Video tayyorlanmoqda...")
    create_video()

    print("VIDEO TAYYOR: shorts.mp4")

if __name__ == "__main__":
    main()
