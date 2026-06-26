"""Phase-4 smoke: the bot package and its Phase-4 modules import."""


def test_aiwip_bot_imports():
    import aiwip_bot  # noqa: F401


def test_phase4_modules_import():
    import aiwip_bot.cards  # noqa: F401
    import aiwip_bot.authz  # noqa: F401
    import aiwip_bot.handlers  # noqa: F401
    import aiwip_bot.digest  # noqa: F401
