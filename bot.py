import discord
from discord.ext import commands, tasks
import json
from datetime import datetime, timedelta
import os
import threading
from flask import Flask

# --- Flask Keep-Alive for Render Web Service ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is running!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = threading.Thread(target=run)
    t.start()

# --- Discord Bot Setup ---
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='!', intents=intents)

REMINDERS_FILE = 'reminders.json'

def load_reminders():
    try:
        with open(REMINDERS_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return []

def save_reminders(reminders):
    with open(REMINDERS_FILE, 'w') as f:
        json.dump(reminders, f)

def parse_datetime(dt_str):
    try:
        return datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
    except:
        return None

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')
    reminder_check.start()

@bot.command()
async def reminder(ctx, dt: str, *, text: str):
    """
    Set a reminder.
    Usage: !reminder YYYY-MM-DD HH:MM Task details
    Example: !reminder 2025-08-05 14:30 Doctor appointment
    """
    dt_parsed = parse_datetime(dt)
    if not dt_parsed:
        await ctx.send("Invalid date format! Use YYYY-MM-DD HH:MM (24hr). Example: 2025-08-05 14:30")
        return
    reminders = load_reminders()
    reminders.append({
        "user_id": ctx.author.id,
        "text": text,
        "time": dt,
        "repeat": None,
        "notify_before": []
    })
    save_reminders(reminders)
    await ctx.send(f"Reminder set for {dt}: {text}")

@bot.command()
async def reminders(ctx):
    """
    List your reminders.
    Usage: !reminders
    """
    reminders = load_reminders()
    user_reminders = [r for r in reminders if r['user_id'] == ctx.author.id]
    if not user_reminders:
        await ctx.send("You have no reminders.")
    else:
        msg = ""
        for idx, r in enumerate(user_reminders, 1):
            nb = ', '.join([f"{n}min" for n in r.get('notify_before', [])]) if r.get('notify_before') else 'None'
            rep = r.get('repeat') if r.get('repeat') else 'None'
            msg += f"{idx}. {r['time']}: {r['text']} | Repeat: {rep} | Notify before: {nb}\n"
        await ctx.send(f"Your reminders:\n{msg}")

@bot.command()
async def repeatreminder(ctx, interval: str, dt: str, *, text: str):
    """
    Set a repeated reminder.
    Usage: !repeatreminder daily 2025-08-05 14:30 Meeting
    Intervals: daily, weekly
    """
    dt_parsed = parse_datetime(dt)
    if not dt_parsed or interval not in ["daily", "weekly"]:
        await ctx.send("Invalid format! Use: !repeatreminder [daily|weekly] YYYY-MM-DD HH:MM Task")
        return
    reminders = load_reminders()
    reminders.append({
        "user_id": ctx.author.id,
        "text": text,
        "time": dt,
        "repeat": interval,
        "notify_before": []
    })
    save_reminders(reminders)
    await ctx.send(f"Repeating reminder set for {dt} ({interval}): {text}")

@bot.command()
async def notifyme(ctx, before: str, idx: int):
    """
    Add a 'remind me before' notification to a reminder.
    Usage: !notifyme 1h 2
    (Sets a notification for reminder #2 one hour before)
    """
    reminders = load_reminders()
    user_reminders = [r for r in reminders if r['user_id'] == ctx.author.id]
    if idx < 1 or idx > len(user_reminders):
        await ctx.send("Invalid reminder number.")
        return
    r = user_reminders[idx-1]
    # Parse 'before' as minutes/hours/days (e.g., '30m', '2h', '1d')
    mult = {'m': 1, 'h': 60, 'd': 1440}
    try:
        unit = before[-1]
        value = int(before[:-1])
        minutes = value * mult[unit]
    except:
        await ctx.send("Invalid time format! Use numbers followed by m (minutes), h (hours), or d (days), e.g., 10m, 2h, 1d")
        return
    # Add notify_before (in minutes)
    for rem in reminders:
        if rem == r:
            rem.setdefault('notify_before', []).append(minutes)
    save_reminders(reminders)
    await ctx.send(f"Will remind you {before} before for reminder #{idx}")

@tasks.loop(minutes=1)
async def reminder_check():
    reminders = load_reminders()
    now = datetime.now()
    to_remove = []
    for idx, r in enumerate(reminders):
        dt = parse_datetime(r['time'])
        user = bot.get_user(r['user_id'])
        # Notify 'before'
        for nb in r.get('notify_before', []):
            notify_time = dt - timedelta(minutes=nb)
            # Use seconds for granularity, but we check every minute so 59s fudge
            if notify_time <= now < notify_time + timedelta(seconds=59):
                if user:
                    try:
                        await user.send(f"⏰ (Pre-Reminder) **{r['text']}** at {r['time']}")
                    except:
                        pass
        # Main reminder
        if dt <= now < dt + timedelta(seconds=59):
            if user:
                try:
                    await user.send(f"🔔 Reminder: **{r['text']}** (scheduled for {r['time']})")
                except:
                    pass
            # Handle repeat
            if r.get('repeat') == 'daily':
                next_dt = dt + timedelta(days=1)
                r['time'] = next_dt.strftime("%Y-%m-%d %H:%M")
            elif r.get('repeat') == 'weekly':
                next_dt = dt + timedelta(weeks=1)
                r['time'] = next_dt.strftime("%Y-%m-%d %H:%M")
            else:
                to_remove.append(idx)
    # Remove non-repeating reminders
    reminders = [r for i, r in enumerate(reminders) if i not in to_remove]
    save_reminders(reminders)

# --- Run everything! ---
keep_alive()
bot.run(os.environ['DISCORD_TOKEN'])
