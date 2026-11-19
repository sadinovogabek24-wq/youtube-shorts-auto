
import os
import asyncio
import textwrap
from google import genai
import edge_tts
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import ImageClip, AudioFileClip

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

def create_video(title, script):
    image = Image.new("RGB", (1080, 1920), (12, 20, 45))
    draw = ImageDraw.Draw(image)

    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 65)
        small = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 48)
    except:
        font = ImageFont.load_default()
        small = font

    draw.text((70, 300), "SIRLAR OLAMI", font=font, fill="yellow")
    y = 650
    for line in textwrap.wrap(title, width=22):
        draw.text((70, y), line, font=font, fill="white")
        y += 100

    y += 100
    for line in textwrap.wrap(script, width=32):
        draw.text((70, y), line, font=small, fill="white")
        y += 75
        if y > 1600:
            break

    image.save("background.png")

    async def make_audio():
        voice = edge_tts.Communicate(
            script, "uz-UZ-SardorNeural")
        await voice.save("voice.mp3")

    asyncio.run(make_audio())

    audio = AudioFileClip("voice.mp3")
    video = ImageClip("background.png").set_duration(audio.duration)
    video = video.set_audio(audio)

    video.write_videofile(
        "shorts.mp4",
        fps=24,
        codec="libx264",
        audio_codec="aac"
    )

def main():
    prompt = """
    O'zbek tilida juda qiziqarli, hayratlanarli va
    tekshirish mumkin bo'lgan bitta fakt yoz.
    Javobni quyidagi shaklda ber:
    SARLAVHA: ...
    MATN: ...
    Matn 80-100 so'z bo'lsin.
    """
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )

    result = response.text
    title = result.split("SARLAVHA:")[1].split("MATN:")[0].strip()
    script = result.split("MATN:")[1].strip()

    create_video(title, script)

if __name__ == "__main__":
    main()
