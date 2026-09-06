import discord


def score_embed(title: str, description: str, color: discord.Color = discord.Color.green()) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=color)
    return embed


def transaction_embed(title: str, description: str) -> discord.Embed:
    return discord.Embed(title=title, description=description, color=discord.Color.blurple())


def error_embed(message: str) -> discord.Embed:
    return discord.Embed(title="Error", description=message, color=discord.Color.red())
