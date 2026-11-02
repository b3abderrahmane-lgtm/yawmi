"""يومي — تنبيهات تيليغرام.

يقرأ الجدول الذي يرفعه التطبيق إلى متغيّر المستودع YAWMI_EVENTS،
ثم ينتظر موعد كل مهمة ويرسل تنبيهاً قبلها بـ LEAD_MIN دقائق.

كل تشغيل يتكفّل بنافذة زمنية محدّدة ولا يخرج قبل نهايتها،
فلا تتداخل التشغيلات ولا يتكرّر تنبيه:
  - التشغيل المجدول (الدقيقة 35 من كل ساعة): الساعتان التاليتان؛ وما يأتي من تشغيلات
    أثناءه ينتظر دوره، فإن أسقط GitHub تشغيلاً غطّاه الذي بعده.
  - التشغيل اليدوي (من التطبيق بعد المزامنة): من لحظة المزامنة حتى نهاية الساعة التالية.
"""
import datetime
import json
import os
import sys
import time
import urllib.parse
import urllib.request

H = 3600
LEAD = int(os.environ.get("LEAD_MIN", "5") or 5) * 60
LATE = 20 * 60          # تنبيه تأخّر GitHub في تشغيله يُرسل إن لم يتجاوز 20 دقيقة
WD = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]

TOKEN = os.environ.get("TG_TOKEN", "")
CHAT = os.environ.get("TG_CHAT", "")
DRY = os.environ.get("DRY_RUN") == "1"
clock = time.time
sleep = time.sleep


def hm(m):
    m = int(m)
    return "%02d:%02d" % ((m // 60) % 24, m % 60)


def send(text, silent=False):
    if DRY:
        print(("[صامت] " if silent else "[تنبيه] ") + text.replace("\n", " | "))
        return True
    data = urllib.parse.urlencode({
        "chat_id": CHAT, "text": text,
        "disable_notification": "true" if silent else "false",
        "disable_web_page_preview": "true",
    }).encode()
    for attempt in range(3):
        try:
            with urllib.request.urlopen("https://api.telegram.org/bot%s/sendMessage" % TOKEN, data, timeout=20) as r:
                if r.status == 200:
                    return True
        except Exception as e:  # noqa: BLE001
            print("telegram error:", e)
            sleep(3 * (attempt + 1))
    return False


def window(event, frm, now):
    if event == "workflow_dispatch":
        try:
            ws = int(frm)
            if not (now - 3 * H < ws <= now + 60):
                ws = int(now)
        except (TypeError, ValueError):
            ws = int(now)
        return ws, (ws // H) * H + 2 * H
    ws = int((now + 1800) // H) * H
    return ws, ws + 2 * H


def build_jobs(pay):
    jobs = []
    days = pay.get("days") or []
    for day in days:
        z, d = int(day["z"]), day["d"]
        ev = day.get("e") or []
        wd = WD[datetime.date(*map(int, d.split("-"))).weekday()]
        lines = ["📋 جدول %s %s" % (wd, d)]
        for s, dur, title, meta, done, alert in ev:
            lines.append("%s–%s  %s%s" % (hm(s), hm(s + dur), title, " ✓" if done else ""))
        jobs.append((z, "digest", "\n".join(lines)))
        for s, dur, title, meta, done, alert in ev:
            if not alert or done:
                continue
            txt = "⏰ %s–%s\n%s" % (hm(s), hm(s + dur), title)
            if meta:
                txt += "\n" + meta
            jobs.append((z + int(s) * 60 - LEAD, "alert", txt))
    if days:
        last = days[-1]
        jobs.append((int(last["z"]) + 12 * H, "stale",
                     "⚠️ هذا آخر يوم في الجدول المرفوع. افتح تطبيق «يومي» ليُرفع جدول الأيام القادمة."))
    jobs.sort(key=lambda j: j[0])
    return jobs


def main():
    raw = os.environ.get("YAWMI_EVENTS", "").strip()
    now = clock()
    ws, we = window(os.environ.get("GH_EVENT", "schedule"), os.environ.get("FROM", ""), now)
    print("window: %s → %s (UTC)" % (time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(ws)),
                                     time.strftime("%H:%M:%S", time.gmtime(we))))
    if not raw:
        print("YAWMI_EVENTS فارغ — افتح التطبيق واضغط «حفظ ومزامنة الآن».")
        return 0
    if not DRY and (not TOKEN or not CHAT):
        print("TG_TOKEN أو TG_CHAT غير مضبوط في Secrets.")
        return 1
    pay = json.loads(raw)
    print("synced: %s · days: %d" % (time.strftime("%Y-%m-%d %H:%M", time.gmtime(pay.get("gen", 0))), len(pay.get("days") or [])))
    jobs = [j for j in build_jobs(pay) if ws <= j[0] < we]
    print("in window: %d" % len(jobs))
    sent = 0
    for t, kind, text in jobs:
        now = clock()
        if t > now:
            sleep(t - now)
        elif now - t > LATE:
            print("skip (late %ds): %s" % (now - t, text.split("\n")[1] if "\n" in text else text))
            continue
        if send(text, silent=(kind == "digest")):
            sent += 1
            print("sent %s %s" % (time.strftime("%H:%M:%S", time.gmtime(clock())), kind))
    rest = we - clock()
    if rest > 0:
        sleep(rest)     # البقاء حتى نهاية النافذة يمنع التداخل مع التشغيل التالي
    print("done · sent %d" % sent)
    return 0


if __name__ == "__main__":
    sys.exit(main())
