import discord
from discord import app_commands
from discord.ext import tasks
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

bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

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
    try:
        synced = await tree.sync()
        print(f'Synced {len(synced)} slash commands.')
    except Exception as e:
        print(f'Error syncing commands: {e}')
    reminder_check.start()

# --- SLASH COMMANDS ---

@tree.command(name="reminder", description="Set a reminder (YYYY-MM-DD HH:MM Task)")
@app_commands.describe(date="Date in YYYY-MM-DD", time="Time in 24h format HH:MM", text="Task to remind you about")
async def reminder(interaction: discord.Interaction, date: str, time: str, text: str):
    dt_str = f"{date} {time}"
    dt_parsed = parse_datetime(dt_str)
    if not dt_parsed:
        await interaction.response.send_message("Invalid date format! Use YYYY-MM-DD HH:MM (24hr). Example: 2025-08-05 14:30", ephemeral=True)
        return
    reminders = load_reminders()
    reminders.append({
        "user_id": interaction.user.id,
        "text": text,
        "time": dt_str,
        "repeat": None,
        "notify_before": []
    })
    save_reminders(reminders)
    await interaction.response.send_message(f"Reminder set for {dt_str}: {text}", ephemeral=True)

@tree.command(name="reminders", description="List your reminders")
async def reminders(interaction: discord.Interaction):
    reminders = load_reminders()
    user_reminders = [r for r in reminders if r['user_id'] == interaction.user.id]
    if not user_reminders:
        await interaction.response.send_message("You have no reminders.", ephemeral=True)
    else:
        msg = ""
        for idx, r in enumerate(user_reminders, 1):
            nb = ', '.join([f"{n}min" for n in r.get('notify_before', [])]) if r.get('notify_before') else 'None'
            rep = r.get('repeat') if r.get('repeat') else 'None'
            msg += f"{idx}. {r['time']}: {r['text']} | Repeat: {rep} | Notify before: {nb}\n"
        await interaction.response.send_message(f"Your reminders:\n{msg}", ephemeral=True)

@tree.command(name="repeatreminder", description="Set a repeated reminder (daily/weekly)")
@app_commands.describe(interval="Repeat interval: daily or weekly", date="Date in YYYY-MM-DD", time="Time in 24h format HH:MM", text="Task")
async def repeatreminder(interaction: discord.Interaction, interval: str, date: str, time: str, text: str):
    dt_str = f"{date} {time}"
    dt_parsed = parse_datetime(dt_str)
    if not dt_parsed or interval not in ["daily", "weekly"]:
        await interaction.response.send_message("Invalid format! Use: interval: daily/weekly, date: YYYY-MM-DD, time: HH:MM (24hr), text: task", ephemeral=True)
        return
    reminders = load_reminders()
    reminders.append({
        "user_id": interaction.user.id,
        "text": text,
        "time": dt_str,
        "repeat": interval,
        "notify_before": []
    })
    save_reminders(reminders)
    await interaction.response.send_message(f"Repeating reminder set for {dt_str} ({interval}): {text}", ephemeral=True)

@tree.command(name="notifyme", description="Add a notification before a reminder")
@app_commands.describe(before="e.g. 1h, 30m, 1d", idx="Reminder number as shown in /reminders")
async def notifyme(interaction: discord.Interaction, before: str, idx: int):
    reminders = load_reminders()
    user_reminders = [r for r in reminders if r['user_id'] == interaction.user.id]
    if idx < 1 or idx > len(user_reminders):
        await interaction.response.send_message("Invalid reminder number.", ephemeral=True)
        return
    r = user_reminders[idx-1]
    mult = {'m': 1, 'h': 60, 'd': 1440}
    try:
        unit = before[-1]
        value = int(before[:-1])
        minutes = value * mult[unit]
    except:
        await interaction.response.send_message("Invalid time format! Use numbers followed by m (minutes), h (hours), or d (days), e.g., 10m, 2h, 1d", ephemeral=True)
        return
    for rem in reminders:
        if rem == r:
            rem.setdefault('notify_before', []).append(minutes)
    save_reminders(reminders)
    await interaction.response.send_message(f"Will remind you {before} before for reminder #{idx}", ephemeral=True)

@tasks.loop(minutes=1)
async def reminder_check():
    reminders = load_reminders()
    now = datetime.now()
    to_remove = []
    for idx, r in enumerate(reminders):
        dt = parse_datetime(r['time'])
        user = await bot.fetch_user(r['user_id'])
        # Notify 'before'
        for nb in r.get('notify_before', []):
            notify_time = dt - timedelta(minutes=nb)
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
            if r.get('repeat') == 'daily':
                next_dt = dt + timedelta(days=1)
                r['time'] = next_dt.strftime("%Y-%m-%d %H:%M")
            elif r.get('repeat') == 'weekly':
                next_dt = dt + timedelta(weeks=1)
                r['time'] = next_dt.strftime("%Y-%m-%d %H:%M")
            else:
                to_remove.append(idx)
    reminders = [r for i, r in enumerate(reminders) if i not in to_remove]
    save_reminders(reminders)

# --- Run everything! ---
keep_alive()
bot.run(os.environ['DISCORD_TOKEN'])

