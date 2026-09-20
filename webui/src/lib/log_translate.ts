/**
 * Plain-English translator for technical log lines.
 *
 * Mirrors the Python ``airscope.ui.log_translate.plain_english()`` exactly.
 * Rules are applied in order; first match wins.
 */

interface Rule {
  technical: string;
  friendly: string;
}

const RULES: Rule[] = [
  // ── handshake / 4-way ──────────────────────────────────────────
  { technical: "Got EAPOL M1", friendly: "Handshake step 1 captured" },
  { technical: "Got EAPOL M2", friendly: "Handshake step 2 captured" },
  { technical: "Got EAPOL M3", friendly: "Handshake step 3 captured" },
  { technical: "Got EAPOL M4", friendly: "Handshake step 4 captured" },
  { technical: "Crackable pair confirmed", friendly: "Complete handshake — ready to crack" },
  { technical: "Handshake already saved", friendly: "Already have a capture for this network" },
  { technical: "HANDSHAKE captured", friendly: "Handshake captured — ready to crack" },
  { technical: "✓ HANDSHAKE", friendly: "Handshake captured — ready to crack" },
  // ── PMKID ──────────────────────────────────────────────────────
  { technical: "PMKID found", friendly: "Key fingerprint captured silently" },
  { technical: "PMKID captured", friendly: "Key fingerprint captured silently" },
  { technical: "✓ PMKID", friendly: "Key fingerprint captured silently" },
  // ── WEP ────────────────────────────────────────────────────────
  { technical: "WEP KEY captured", friendly: "WEP key captured" },
  { technical: "✓ WEP KEY", friendly: "WEP key captured" },
  { technical: "Decloaked Hidden Network", friendly: "Hidden network revealed" },
  // ── WPS ────────────────────────────────────────────────────────
  { technical: "WPS PIN found", friendly: "WPS PIN found" },
  { technical: "✓ WPS PIN", friendly: "WPS PIN found" },
  { technical: "WPS PSK (via PushButton)", friendly: "Password recovered via WPS button" },
  { technical: "WPS PSK found", friendly: "Password recovered via WPS" },
  { technical: "✓ WPS PSK", friendly: "Password recovered via WPS" },
  { technical: "WPS locked", friendly: "Router has locked WPS — too many attempts" },
  // ── SAE / WPA3 ────────────────────────────────────────────────
  { technical: "SAE captured", friendly: "WPA3 login exchange captured" },
  { technical: "✓ SAE", friendly: "WPA3 login exchange captured" },
  // ── EvilTwin ───────────────────────────────────────────────────
  { technical: "PSK recovered", friendly: "Password found!" },
  { technical: "Password found", friendly: "Password found!" },
  // ── deauth / disassoc ──────────────────────────────────────────
  { technical: "Sending deauth to client", friendly: "Disconnecting a device from the network" },
  { technical: "Deauth of", friendly: "Disconnecting devices from" },
  { technical: "Deauth stopped", friendly: "Deauthentication stopped" },
  { technical: "✓ Deauth provoked a crackable handshake", friendly: "Handshake captured after disconnecting devices" },
  // ── scanning / channel ─────────────────────────────────────────
  { technical: "Channel hopping", friendly: "Scanning across all channels" },
  { technical: "Tuned to channel", friendly: "Switched to channel" },
  { technical: "Tried to tune to channel", friendly: "Attempted to switch to channel" },
  { technical: "Passively listening", friendly: "Listening for traffic silently" },
  // ── target / focus ─────────────────────────────────────────────
  { technical: "Target acquired", friendly: "Locked onto target network" },
  { technical: "Encryption:", friendly: "Encryption:" },
  { technical: "BSSID:", friendly: "BSSID:" },
  // ── PMF ────────────────────────────────────────────────────────
  { technical: "PMF Required", friendly: "Network requires management frame protection" },
  { technical: "Deauth attacks have been disabled", friendly: "Disconnect attacks blocked — network uses management protection" },
  // ── WEP attacks ────────────────────────────────────────────────
  { technical: "ChopChop", friendly: "Packet forgery attack" },
  { technical: "ARP Replay", friendly: "Replaying ARP packets to generate data" },
  // ── EvilTwin campaign ──────────────────────────────────────────
  { technical: "EvilTwin of", friendly: "Fake network targeting" },
  { technical: "EvilTwin stopped", friendly: "Fake network attack stopped" },
  { technical: "twin live on ch", friendly: "Fake network running on channel" },
  // ── WPS attacks ────────────────────────────────────────────────
  { technical: "WPS PIN brute started", friendly: "Trying common WPS PINs against the router" },
  { technical: "WPS PushButton", friendly: "WPS button-press detection" },
  // ── SAE capture ────────────────────────────────────────────────
  { technical: "SAE capture on", friendly: "Capturing WPA3 login from" },
  // ── batch ──────────────────────────────────────────────────────
  { technical: "Batch already running", friendly: "An automated attack sequence is already running" },
  { technical: "Nothing to attack", friendly: "No targetable networks in the selection" },
  { technical: "Batch done", friendly: "Automated attack sequence finished" },
  // ── silence ────────────────────────────────────────────────────
  { technical: "AP Silenced", friendly: "Network notifications paused" },
  { technical: "AP UnSilenced", friendly: "Network notifications resumed" },
  // ── capture events ─────────────────────────────────────────────
  { technical: "Existing captures in", friendly: "Previous captures found in" },
];

/**
 * Translate a technical log line to plain English.
 * Returns the original line if no rule matches.
 */
export function plainEnglish(line: string): string {
  for (const rule of RULES) {
    if (line.includes(rule.technical)) {
      return rule.friendly;
    }
  }
  return line;
}
