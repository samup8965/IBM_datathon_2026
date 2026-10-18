"""Record a demo video of the live Outage Alert website: a fixed, paced walkthrough with
nothing drawn on screen (the narration is spoken over it).

Usage (from the repo root, with the backend running on the z17):
    uv run --with playwright --with imageio-ffmpeg python scripts/record_demo.py
    uv run --with playwright --with imageio-ffmpeg python scripts/record_demo.py \
        --url http://148.100.108.186:8000 --out-dir ~/demo_video

Writes to --out-dir:
    outage_alert_demo.mp4   1920x1080 video
    timeline.txt            when each step starts, to line the narration up
    snapshot.json           the live numbers on screen at recording time

First time only: uvx --from playwright playwright install chromium
"""

import argparse
import json
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

WIDTH, HEIGHT = 1920, 1080
ZOOM = 1.25  # the page is designed for ~1300px; zooming fills 1080p with crisp text


def fetch(url):
    with urllib.request.urlopen(url, timeout=15) as r:
        return json.load(r)


def snapshot(base):
    """The numbers the video will show, for writing the narration."""
    regions = fetch(base + "/v1/regions")
    summary = fetch(base + "/v1/households/summary")["regions"]
    health = fetch(base + "/health")
    scored = [r for r in regions if r["status"] == "ok"]
    by_id = {r["region_id"]: r for r in regions}
    return {
        "health": health,
        "states_scored": len(scored),
        "critical": sum(r["risk_level"] == "critical" for r in scored),
        "outages_now": sum(bool(r["outage_in_progress"]) for r in scored),
        "urgent_households": sum(h["urgent"] for h in summary),
        "states_shown": {code: by_id[code] for code in ["VE-A", "VE-S", "VE-E", "VE-Z"]},
        "households": {h["region_id"]: h for h in summary if h["region_id"] in ["VE-S", "VE-E"]},
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://148.100.108.186:8000")
    parser.add_argument("--out-dir", type=Path, default=Path("demo_video"))
    args = parser.parse_args()
    base = args.url.rstrip("/")
    out = args.out_dir.expanduser()
    out.mkdir(parents=True, exist_ok=True)

    (out / "snapshot.json").write_text(json.dumps(snapshot(base), indent=2, ensure_ascii=False))
    timeline = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(
            viewport={"width": WIDTH, "height": HEIGHT},
            record_video_dir=str(out / "raw"),
            record_video_size={"width": WIDTH, "height": HEIGHT},
        )
        context.add_init_script(
            f"document.addEventListener('DOMContentLoaded', () => "
            f"document.documentElement.style.zoom = '{ZOOM}');"
        )
        page = context.new_page()
        start = time.monotonic()

        def step(text, hold):
            timeline.append((time.monotonic() - start, text))
            print(f"{timeline[-1][0]:6.1f}s  {text}", flush=True)
            page.wait_for_timeout(int(hold * 1000))

        def glide_to(selector, steps=30):
            box = page.locator(selector).bounding_box()
            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=steps)

        def scroll_to(y, hold=1.2):
            page.evaluate(f"window.scrollTo({{top: {y}, behavior: 'smooth'}})")
            page.wait_for_timeout(int(hold * 1000))

        page.goto(base + "/")
        page.wait_for_selector(".gauge")
        page.mouse.move(WIDTH - 40, 40)
        step("1. Overview: live badge, headline, key numbers, map and Caracas forecast", 7)

        for code in ["VE-V", "VE-K", "VE-F", "VE-S"]:
            glide_to(f"[data-region='{code}']")
            page.wait_for_timeout(1300)
        step("2. Hovering the map: each state's level and chance of an outage", 1)

        page.click("[data-region='VE-S']", force=True)
        step("3. Táchira selected: gauge, risk badge, reasons, grid conditions, actions", 8)

        glide_to("[data-profile='medical']")
        page.click("[data-profile='medical']")
        step("4. Medical needs: tailored steps, backup battery, medical households nearby", 8)

        scroll_to(page.evaluate("document.querySelector('.ranking').offsetTop * %s - 40" % ZOOM), 1.5)
        step("5. Ranking: all states, highest risk first", 5)
        glide_to("[data-pick='VE-E']", steps=20)
        page.click("[data-pick='VE-E']")
        scroll_to(0, 1.5)
        step("6. Barinas picked from the list, shown at the top", 6)

        glide_to("#zoom-in", steps=20)
        page.click("#zoom-in")
        page.wait_for_timeout(700)
        page.click("#zoom-in")
        step("7. Zooming into the map", 2.5)
        page.click("#fit")
        page.wait_for_timeout(800)

        page.click("[data-region='VE-Z']", force=True)
        step("8. Amazonas: too few networks, so no forecast rather than a guess", 5)

        glide_to("#mode", steps=25)
        page.click("#mode")
        page.wait_for_selector("#simulate")
        step("9. Demo simulation: fictional values to show how guidance changes", 3)
        for _ in range(3):
            glide_to("#simulate", steps=12)
            page.click("#simulate")
            page.wait_for_timeout(1600)
        step("10. Simulated up to Critical", 3)
        glide_to("#mode", steps=20)
        page.click("#mode")
        page.wait_for_selector(".pill.live")
        step("11. Back to live data", 3)

        page.goto(base + "/health")
        step("12. Proof: the server reports scoring_device nnpa (Telum AI accelerator)", 6)
        page.goto(base + "/")
        page.wait_for_selector(".gauge")
        step("13. Closing on the live overview", 5)
        timeline.append((time.monotonic() - start, "end"))

        video = page.video.path()
        context.close()
        browser.close()

    with open(out / "timeline.txt", "w") as f:
        for t, text in timeline:
            f.write(f"{int(t // 60)}:{t % 60:04.1f}  {text}\n")

    # webm -> mp4 (H.264) so it drops into any video editor
    import imageio_ffmpeg

    mp4 = out / "outage_alert_demo.mp4"
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-i", video,
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-r", "30", str(mp4)],
                   check=True)
    shutil.rmtree(out / "raw", ignore_errors=True)
    print(f"Saved {mp4}, {out / 'timeline.txt'}, {out / 'snapshot.json'}")


if __name__ == "__main__":
    main()
