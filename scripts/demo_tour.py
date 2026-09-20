"""Demo tour recorder: walks the dashboard and saves frames for the README GIF.

Flow: Devices (empty/demo state) -> Scanner (live) -> Ctrl+K palette ->
Target (start attack, magenta running) -> Vault (crack a capture) ->
Reports (HTML preview). Assemble with:
  ffmpeg -framerate 2 -i /tmp/tour/f%03d.png -vf "scale=800:-1:flags=lanczos,\
split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse" assets/demo-tour.gif
"""
import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

URL = "http://127.0.0.1:8770/"
OUT = Path("/tmp/tour")
SHOT = {"n": 0}


async def snap(page, pause_s=1.5):
    await page.wait_for_timeout(int(pause_s * 1000))
    SHOT["n"] += 1
    await page.screenshot(path=str(OUT / f"f{SHOT['n']:03d}.png"))


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("f*.png"):
        old.unlink()
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1000, "height": 700})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        # 1. Devices: empty state + demo strip
        await page.goto(URL + "#/devices", wait_until="networkidle")
        await snap(page, 2.0)

        # 2. Scanner: live wandering table
        await page.goto(URL + "#/", wait_until="networkidle")
        await snap(page, 2.0)
        await snap(page, 2.0)

        # 3. Command palette
        await page.keyboard.press("Control+k")
        await page.wait_for_timeout(600)
        await page.keyboard.type("target home", delay=40)
        await page.wait_for_timeout(600)
        await snap(page, 1.0)
        await page.keyboard.press("Escape")

        # 4. Target: launch a PMKID attack, watch it run magenta
        await page.goto(URL + "#/target/aa:bb:cc:dd:ee:01", wait_until="networkidle")
        await page.wait_for_timeout(1500)
        await snap(page, 1.0)
        await page.locator(".btnrow .attack-btn", has_text="PMKID").click()
        await page.wait_for_selector(".attack-btn.running", timeout=10000)
        await snap(page, 2.0)
        await snap(page, 2.0)
        # let the demo attack finish saving its capture
        await page.wait_for_timeout(6000)

        # 5. Vault: crack the fresh capture with the demo wordlist
        await page.goto(URL + "#/vault", wait_until="networkidle")
        await page.wait_for_timeout(1500)
        await snap(page, 1.0)
        await page.locator("td.actions input").first.fill("/tmp/words.txt")
        await page.locator("button:has-text('Crack')").first.click()
        await snap(page, 2.5)
        await snap(page, 2.5)
        await page.wait_for_timeout(3000)
        await snap(page, 1.5)

        # 6. Reports incl. HTML preview
        await page.goto(URL + "#/reports", wait_until="networkidle")
        await page.wait_for_timeout(2500)
        await snap(page, 1.5)

        print("frames:", SHOT["n"])
        print("page errors:", errors if errors else "none")
        await browser.close()


asyncio.run(main())
