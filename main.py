
def main():
    print("Yangi ikki qismli hikoya yaratilmoqda...")
    episode = create_episode()

    EPISODE_FILE.write_text(
        json.dumps(episode, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    for part_number in (1, 2):
        story_key = f"part{part_number}"
        visuals_key = f"visuals{part_number}"

        story = episode[story_key]
        visuals = episode.get(
            visuals_key, DEFAULT_VIDEO_QUERIES
        )

        print(f"\n========== {part_number}-QISM ==========")

        Path("story.txt").write_text(
            story, encoding="utf-8"
        )

        print("O'zbekcha erkak ovozi yaratilmoqda...")
        create_voice(story)

        print("9:16 video tayyorlanmoqda...")
        create_video(story, visuals)

        print("YouTube kanaliga yuklanmoqda...")
        upload_to_youtube(part_number)

        print(f"TAYYOR: {part_number}-qism yuklandi.")

    print("IKKALA QISM HAM TAYYOR!")


if __name__ == "__main__":
    main()
