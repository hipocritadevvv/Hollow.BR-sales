import discord
from discord.ext import commands
import json
import os
from datetime import datetime

# ─────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────
import os
BOT_TOKEN          = os.environ["TOKEN"]
ADMIN_ROLE         = "Admin"
LOG_CHANNEL_ID     = int(os.environ["LOG_CHANNEL_ID"])
TICKET_CATEGORY_ID = int(os.environ["TICKET_CATEGORY_ID"])
# ─────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

STOCK_FILE = "stock.json"


# ══════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════

def load_stock() -> dict:
    if not os.path.exists(STOCK_FILE):
        return {}
    with open(STOCK_FILE, "r") as f:
        return json.load(f)

def save_stock(data: dict):
    with open(STOCK_FILE, "w") as f:
        json.dump(data, f, indent=2)

def has_admin_role():
    async def predicate(ctx):
        return any(r.name == ADMIN_ROLE for r in ctx.author.roles)
    return commands.check(predicate)

async def send_log(guild: discord.Guild, embed: discord.Embed):
    ch = guild.get_channel(LOG_CHANNEL_ID)
    if ch:
        await ch.send(embed=embed)

def log_embed(title: str, color: discord.Color, **fields) -> discord.Embed:
    em = discord.Embed(title=title, color=color, timestamp=datetime.utcnow())
    for name, value in fields.items():
        em.add_field(name=name, value=value, inline=False)
    em.set_footer(text="Sales Bot • Logs")
    return em


# ══════════════════════════════════════════
#  VIEWS
# ══════════════════════════════════════════

async def open_ticket(interaction: discord.Interaction, product: str, duration: str):
    guild = interaction.guild
    category = guild.get_channel(TICKET_CATEGORY_ID)
    ticket_name = f"ticket-{interaction.user.name}".lower().replace(" ", "-")

    # Check if user already has an open ticket
    existing = discord.utils.get(guild.text_channels, name=ticket_name)
    if existing:
        await interaction.response.send_message(
            f"❌ You already have an open ticket: {existing.mention}", ephemeral=True
        )
        return

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
    }
    admin_role = discord.utils.get(guild.roles, name=ADMIN_ROLE)
    if admin_role:
        overwrites[admin_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

    channel = await guild.create_text_channel(
        name=ticket_name,
        overwrites=overwrites,
        category=category,
    )

    em = discord.Embed(
        title="🛒 New Order",
        description=(
            f"Hello {interaction.user.mention}! Thank you for your order.\n\n"
            f"**Product:** `{product}`\n"
            f"**Duration:** `{duration}`\n\n"
            "Please send your **payment proof** here.\n"
            "A staff member will review and approve your purchase shortly."
        ),
        color=discord.Color.blurple(),
        timestamp=datetime.utcnow(),
    )
    em.set_footer(text="Use !fechar to close this ticket.")
    await channel.send(embed=em)

    await interaction.response.send_message(
        f"✅ Your ticket has been opened: {channel.mention}", ephemeral=True
    )

    # Log
    log = log_embed(
        "🎫 Ticket Opened",
        discord.Color.green(),
        User=f"{interaction.user} (`{interaction.user.id}`)",
        Product=product,
        Duration=duration,
        Channel=channel.mention,
    )
    await send_log(guild, log)


class DurationSelect(discord.ui.Select):
    def __init__(self, product: str):
        self.product = product
        options = [
            discord.SelectOption(label="Weekly",   emoji="📅", description="7-day access"),
            discord.SelectOption(label="Monthly",  emoji="🗓️", description="30-day access"),
            discord.SelectOption(label="Lifetime", emoji="♾️", description="Permanent access"),
        ]
        super().__init__(placeholder="Select a duration...", options=options)

    async def callback(self, interaction: discord.Interaction):
        await open_ticket(interaction, self.product, self.values[0])


class DurationView(discord.ui.View):
    def __init__(self, product: str):
        super().__init__(timeout=120)
        self.add_item(DurationSelect(product))


class ProductSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Plus",    emoji="⭐", description="Essential features"),
            discord.SelectOption(label="Premium", emoji="💎", description="Full access to all features"),
        ]
        super().__init__(placeholder="Select a product...", options=options)

    async def callback(self, interaction: discord.Interaction):
        product = self.values[0]
        em = discord.Embed(
            title=f"⏱️ Choose Duration — {product}",
            description="Now select how long you want your license:",
            color=discord.Color.gold(),
        )
        await interaction.response.send_message(embed=em, view=DurationView(product), ephemeral=True)


class ProductView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Buy", style=discord.ButtonStyle.success, emoji="🛒", custom_id="buy_button")
    async def buy(self, interaction: discord.Interaction, button: discord.ui.Button):
        em = discord.Embed(
            title="🛍️ Choose a Product",
            description="Select the plan you want to purchase:",
            color=discord.Color.gold(),
        )
        view = discord.ui.View(timeout=120)
        view.add_item(ProductSelect())
        await interaction.response.send_message(embed=em, view=view, ephemeral=True)


# ══════════════════════════════════════════
#  EVENTS
# ══════════════════════════════════════════

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} ({bot.user.id})")
    bot.add_view(ProductView())  # Re-register persistent view on restart


# ══════════════════════════════════════════
#  COMMANDS
# ══════════════════════════════════════════

@bot.command()
@has_admin_role()
async def painel(ctx):
    """Sends the sales panel embed."""
    em = discord.Embed(
        title="🛍️ Our Products",
        description=(
            "Welcome to our store!\n\n"
            "**Choose your plan below** to open a ticket and complete your purchase.\n\n"
            "⭐ **Plus** — Essential features at the best price\n"
            "💎 **Premium** — Full access to all features\n\n"
            "After selecting a plan, choose your preferred duration."
        ),
        color=discord.Color.gold(),
        timestamp=datetime.utcnow(),
    )
    em.set_footer(text="React below to start your order!")
    await ctx.send(embed=em, view=ProductView())
    await ctx.message.delete()


@bot.command()
async def fechar(ctx):
    """Closes the current ticket channel."""
    if "ticket-" not in ctx.channel.name:
        await ctx.send("❌ This command can only be used inside a ticket channel.")
        return

    em = discord.Embed(
        title="🔒 Ticket Closing",
        description="This ticket will be deleted in **5 seconds**.",
        color=discord.Color.red(),
    )
    await ctx.send(embed=em)

    log = log_embed(
        "🔒 Ticket Closed",
        discord.Color.red(),
        Channel=ctx.channel.name,
        ClosedBy=f"{ctx.author} (`{ctx.author.id}`)",
    )
    await send_log(ctx.guild, log)

    await discord.utils.sleep_until(
        datetime.utcnow().__class__.utcnow()
    )
    import asyncio
    await asyncio.sleep(5)
    await ctx.channel.delete()


@bot.command()
@has_admin_role()
async def aprovar(ctx):
    """Approves a purchase and sends the key to the buyer via DM."""
    if "ticket-" not in ctx.channel.name:
        await ctx.send("❌ This command can only be used inside a ticket channel.")
        return

    # Identify the buyer from the channel name (ticket-username)
    ticket_username = ctx.channel.name.replace("ticket-", "")
    buyer = discord.utils.find(
        lambda m: m.name.lower().replace(" ", "-") == ticket_username,
        ctx.guild.members,
    )

    if not buyer:
        await ctx.send("❌ Could not find the buyer. Please deliver the key manually.")
        return

    # Detect product & duration from the first embed in the channel
    product, duration = "Unknown", "Unknown"
    async for msg in ctx.channel.history(oldest_first=True, limit=5):
        if msg.author == bot.user and msg.embeds:
            emb = msg.embeds[0]
            for field in emb.fields:
                if field.name == "Product":
                    product = field.value.strip("`")
                if field.name == "Duration":
                    duration = field.value.strip("`")
            break

    # Pick a key from stock
    stock = load_stock()
    keys = stock.get(product, [])
    if not keys:
        await ctx.send(f"❌ No stock available for **{product}**. Add keys with `!addstock {product} <key>`.")
        return

    key = keys.pop(0)
    stock[product] = keys
    save_stock(stock)

    # DM the buyer
    try:
        dm_em = discord.Embed(
            title="✅ Purchase Approved!",
            description=(
                f"Your order has been approved by our team. Here is your key:\n\n"
                f"**Product:** `{product}`\n"
                f"**Duration:** `{duration}`\n"
                f"**Key:** ||`{key}`||\n\n"
                "Thank you for your purchase! If you need help, open a new ticket."
            ),
            color=discord.Color.green(),
            timestamp=datetime.utcnow(),
        )
        await buyer.send(embed=dm_em)
        await ctx.send(f"✅ Key delivered to {buyer.mention} via DM. Remaining stock for **{product}**: `{len(keys)}`.")
    except discord.Forbidden:
        await ctx.send(f"⚠️ Could not DM {buyer.mention}. Please deliver the key manually: ||`{key}`||")

    # Log
    log = log_embed(
        "✅ Purchase Approved",
        discord.Color.green(),
        Buyer=f"{buyer} (`{buyer.id}`)",
        Product=product,
        Duration=duration,
        ApprovedBy=f"{ctx.author} (`{ctx.author.id}`)",
        RemainingStock=str(len(keys)),
    )
    await send_log(ctx.guild, log)


@bot.command()
@has_admin_role()
async def addstock(ctx, product: str, *, key: str):
    """Adds a key to the stock. Usage: !addstock <PRODUCT> <KEY>"""
    stock = load_stock()
    if product not in stock:
        stock[product] = []
    stock[product].append(key)
    save_stock(stock)

    await ctx.send(f"✅ Key added to **{product}**. Total keys: `{len(stock[product])}`.")

    log = log_embed(
        "📦 Stock Added",
        discord.Color.blurple(),
        Product=product,
        Key=f"||`{key}`||",
        AddedBy=f"{ctx.author} (`{ctx.author.id}`)",
        TotalKeys=str(len(stock[product])),
    )
    await send_log(ctx.guild, log)


@bot.command(name="stock")
@has_admin_role()
async def view_stock(ctx, product: str = None):
    """Shows available stock. Usage: !stock OR !stock <PRODUCT>"""
    stock = load_stock()

    if product:
        keys = stock.get(product, [])
        em = discord.Embed(
            title=f"📦 Stock — {product}",
            description=f"`{len(keys)}` key(s) available." if keys else "❌ No keys available.",
            color=discord.Color.blurple(),
            timestamp=datetime.utcnow(),
        )
        if keys:
            em.add_field(
                name="Keys",
                value="\n".join([f"||`{k}`||" for k in keys]) or "None",
                inline=False,
            )
        await ctx.send(embed=em)
    else:
        em = discord.Embed(
            title="📦 Full Stock Overview",
            color=discord.Color.blurple(),
            timestamp=datetime.utcnow(),
        )
        if not stock:
            em.description = "No products in stock."
        else:
            for prod, keys in stock.items():
                em.add_field(name=prod, value=f"`{len(keys)}` key(s)", inline=True)
        await ctx.send(embed=em)


@bot.command()
@has_admin_role()
async def removerstock(ctx, *, key: str):
    """Removes a specific key from stock. Usage: !removerstock <KEY>"""
    stock = load_stock()
    removed = False

    for product, keys in stock.items():
        if key in keys:
            keys.remove(key)
            stock[product] = keys
            save_stock(stock)
            removed = True
            await ctx.send(f"✅ Key removed from **{product}**. Remaining: `{len(keys)}`.")

            log = log_embed(
                "🗑️ Stock Removed",
                discord.Color.orange(),
                Product=product,
                Key=f"||`{key}`||",
                RemovedBy=f"{ctx.author} (`{ctx.author.id}`)",
                RemainingKeys=str(len(keys)),
            )
            await send_log(ctx.guild, log)
            break

    if not removed:
        await ctx.send("❌ Key not found in any product's stock.")


# ══════════════════════════════════════════
#  ERROR HANDLING
# ══════════════════════════════════════════

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        await ctx.send("❌ You don't have permission to use this command.", delete_after=5)
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Missing argument: `{error.param.name}`. Check the command usage.", delete_after=8)
    else:
        raise error


bot.run(BOT_TOKEN)
