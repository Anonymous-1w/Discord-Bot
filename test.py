import discord
from discord.ext import commands
from discord import app_commands
from pymongo import MongoClient
import requests
import os
from dotenv import load_dotenv
import re

# Load environment variables
load_dotenv()

# Environment variables
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
LEARNWORLDS_TOKEN = os.getenv("LEARNWORLDS_TOKEN")
LW_CLIENT_ID = os.getenv("LW_CLIENT_ID")
LEARNWORLDS_API_BASE_URL = os.getenv("LEARNWORLDS_API_BASE_URL", "https://courses.altacademy.org/admin/api/v2/users")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")

# Role mapping
ROLE_MAPPING = {
    "Plus User": "Plus User",
    "Premium User": "Premium",
    "Free User": "Member",
}

# MongoDB Connection
try:
    mongo_client = MongoClient(MONGO_URI)
    db = mongo_client["discord_bot"]
    users_collection = db["users"]
    print("[SUCCESS] Connected to MongoDB")
except Exception as e:
    print(f"[ERROR] MongoDB connection failed: {e}")

# Bot setup
class BotClient(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix="/", intents=intents)

    async def setup_hook(self):
        try:
            await self.tree.sync()
            print("[SUCCESS] Slash commands synced successfully")
        except Exception as e:
            print(f"[ERROR] Failed to sync commands: {e}")

# Initialize bot
bot = BotClient()

def fetch_user_tags(email: str) -> list:
    """Fetch user tags from LearnWorlds."""
    try:
        url = f"{LEARNWORLDS_API_BASE_URL}/{email}"
        
        headers = {
            "Authorization": f"Bearer {LEARNWORLDS_TOKEN}",
            "Lw-Client": LW_CLIENT_ID,
            "Accept": "application/json"
        }
        
        response = requests.get(url, headers=headers)
        print(f"[DEBUG] API Response Status: {response.status_code}")
        print(f"[DEBUG] API Response: {response.text}")

        if response.status_code == 200:
            user_data = response.json()
            tags = user_data.get("tags", [])
            print(f"[SUCCESS] Tags fetched for {email}: {tags}")
            return tags
        else:
            print(f"[ERROR] API request failed: {response.status_code}")
            return []
    except Exception as e:
        print(f"[ERROR] Failed to fetch tags: {e}")
        return []

async def assign_roles(guild, member, tags):
    """Assign Discord roles based on LearnWorlds tags."""
    try:
        assigned_roles = []
        for tag in tags:
            if tag in ROLE_MAPPING:
                role_name = ROLE_MAPPING[tag]
                print(f"[DEBUG] Role name mapped from tag: {role_name}")
                role = discord.utils.get(guild.roles, name=role_name)
                if role:
                    await member.add_roles(role)
                    assigned_roles.append(role_name)
                    print(f"[SUCCESS] Assigned role {role_name} to {member.name}")
                else:
                    print(f"[WARNING] Role {role_name} not found in server")
        return assigned_roles
    except Exception as e:
        print(f"[ERROR] Failed to assign roles: {e}")
        return []

@bot.event
async def on_member_join(member):
    """Handle new member joining the server."""
    try:
        print(f"[INFO] New member joined: {member.name}")
        # Send welcome DM asking for email
        await member.send(
            "Welcome to the server! Please reply with your LearnWorlds email address to verify your account."
        )
        print("[INFO] Sent welcome message to new member")

        def check(m):
            return m.author == member and isinstance(m.channel, discord.DMChannel)

        # Wait for email response (5 minute timeout)
        email_message = await bot.wait_for("message", check=check, timeout=300)
        email = email_message.content.strip().lower()

        # Validate email format
        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
            await member.send("❌ Invalid email format. Please try again with a valid email address.")
            return

        # Fetch tags from LearnWorlds
        tags = fetch_user_tags(email)
        
        if not tags:
            await member.send("No LearnWorlds tags found for your email. Please contact an administrator.")
            return

        # Assign roles based on tags
        assigned_roles = await assign_roles(member.guild, member, tags)

        # Save to MongoDB
        users_collection.update_one(
            {"_id": member.id},
            {
                "$set": {
                    "learnworlds_email": email,
                    "discord_tag": str(member),
                    "tags": tags,
                    "assigned_roles": assigned_roles
                }
            },
            upsert=True
        )

        # Send confirmation message
        embed = discord.Embed(
            title="✅ Verification Complete",
            color=discord.Color.green()
        )
        
        embed.add_field(
            name="Email",
            value=email,
            inline=False
        )
        
        if assigned_roles:
            embed.add_field(
                name="Assigned Roles",
                value="\n".join([f"• {role}" for role in assigned_roles]),
                inline=False
            )
        
        await member.send(embed=embed)
        print(f"[SUCCESS] Completed verification for {member.name}")

    except asyncio.TimeoutError:
        await member.send("Verification timeout. Please use the /verify command to verify your email.")
    except Exception as e:
        print(f"[ERROR] Error during member join: {e}")
        await member.send("An error occurred during verification. Please contact an administrator.")

@bot.tree.command(name="verify", description="Verify your email address")
async def verify(interaction: discord.Interaction):
    """Manual verification command."""
    try:
        await interaction.response.send_message(
            "Please check your DMs for verification instructions.",
            ephemeral=True
        )
        await interaction.user.send(
            "Please reply with your LearnWorlds email address to verify your account."
        )

        def check(m):
            return m.author == interaction.user and isinstance(m.channel, discord.DMChannel)

        email_message = await bot.wait_for("message", check=check, timeout=300)
        email = email_message.content.strip().lower()

        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
            await interaction.user.send("❌ Invalid email format. Please try again with a valid email address.")
            return

        tags = fetch_user_tags(email)
        
        if not tags:
            await interaction.user.send("No LearnWorlds tags found for your email. Please contact an administrator.")
            return

        assigned_roles = await assign_roles(interaction.guild, interaction.user, tags)

        users_collection.update_one(
            {"_id": interaction.user.id},
            {
                "$set": {
                    "learnworlds_email": email,
                    "discord_tag": str(interaction.user),
                    "tags": tags,
                    "assigned_roles": assigned_roles
                }
            },
            upsert=True
        )

        embed = discord.Embed(
            title="✅ Verification Complete",
            color=discord.Color.green()
        )
        embed.add_field(name="Email", value=email, inline=False)
        if assigned_roles:
            embed.add_field(
                name="Assigned Roles",
                value="\n".join([f"• {role}" for role in assigned_roles]),
                inline=False
            )
        
        await interaction.user.send(embed=embed)

    except asyncio.TimeoutError:
        await interaction.user.send("Verification timeout. Please try again.")
    except Exception as e:
        print(f"[ERROR] Verification failed: {e}")
        await interaction.user.send("An error occurred during verification. Please contact an administrator.")

@bot.event
async def on_ready():
    """Triggered when the bot is ready."""
    print(f"[SUCCESS] Bot has connected as {bot.user}")
    print(f"[INFO] Connected to {len(bot.guilds)} server(s):")
    for guild in bot.guilds:
        print(f" - {guild.name} (ID: {guild.id})")
    print("[INFO] Bot is ready and operational")

# Run the bot
if __name__ == "__main__":
    bot.run(DISCORD_BOT_TOKEN)
