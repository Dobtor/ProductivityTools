# Dobtor Messaging Base

Provider-agnostic foundation for syncing external messaging platforms
(LINE, Telegram, …) into Odoo 18 Discuss.

This module contains **no platform protocol code**. It provides the shared
skeleton — neutral `discuss.channel` layer, a provider dispatcher, the
`messaging.account` identity store, SSRF-safe media download, generic frontend
(partner card + avatar patches) and the "bind external contact to customer"
wizard.

Platform modules depend on this and implement only the protocol-specific parts:

| Module | Provides |
|--------|----------|
| `dobtor_line_message` | LINE webhook (HMAC verify), `line.api.service`, sticker/profile handling |
| `dobtor_telegram_message` | Telegram webhook (secret_token + IP), `telegram.api.service`, getFile download |

Installing this module alone is safe and inert: no provider is registered, so
all dispatch paths are no-ops until a platform module adds itself.

See [`docs/DESIGN.md`](docs/DESIGN.md) for the full architecture, the LINE↔Telegram
protocol comparison, the migration plan, and Telegram implementation notes.
