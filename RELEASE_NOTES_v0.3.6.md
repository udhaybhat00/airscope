## What's new in v0.3.6

**Midnight color palette:** new electric blue + violet + amber theme replacing the old green/cyan scheme. All screens, splash, signal bars, export HTML, and web dashboard updated.

**Router + adapter endpoint cards restored:** the focus screen mid-band now shows a live adapter card (chipset, MAC, TX/RX flicker) and router card (signal bar, WPS badge, identity chip, probe button) flanking the sparkline dashboard.

**Evil twin fixes:** modal now validates host and punisher selections before dismissing; `_plus_one` BSSID increment fixed (was incrementing a nibble, now correctly increments the full octet).

**Freeze mode bug fixes:** could not unfreeze (auto-freeze re-triggered instantly on sort), empty banner visible on mount, freeze state persisted after AP eviction or screen transition, auto-freeze activated silently when no AP was selected.

**Splash screen fixes:** removed Header for immersive splash, centered text alignment, Start button uses green variant, Uninstall button fully restored, Rich text colors fixed (was using CSS variable syntax that Rich cannot render).

**Scanner fixes:** WPA3 networks now match correctly (trailing space removed), duplicate Binding("s") removed (footer label stuck), signal bar track color synced to palette, unused `_frozen_ap` state removed, `_theme_fg` initialized to prevent AttributeError.

**SAE campaign fixes:** button click handler was missing (only hotkey worked), save failure now logs error instead of claiming success.

**Evil twin finish fix:** now reads AP from `camp.target` instead of `self._target_ap` to avoid showing wrong SSID if user switched targets during campaign.

**Campaign race condition:** `on_screen_resume` no longer re-pins channel when a campaign is active.

**Dead code cleanup:** removed unused `FADE_DURATION_S`, `_NUMERIC_COLS`, `_frozen_ap`, `HORIZONTAL_BREAKPOINTS`, `flash_bacon` typo parameter, `pulse` signal bar parameter, `_ENC_SUFFIX` recreation on every cell render.

**2970 tests pass, lint clean.**
