# Grasse: how it should work

Describes behaviour only. Step 1 of the build order and product decisions (want / own /
not interested) are built; the rest is planned.

## Goal

Watch around 10 B2B suppliers and only hear about what matters: the brands and fragrances you
care about. Over time, grow it into the place where you manage your collection, wishlist and
purchases (personal use, no resale).

## The building blocks

| Thing | What it is | Example |
|---|---|---|
| **Brand** | One canonical name, plus the other spellings suppliers use (aliases). | Yves Saint Laurent (aliases: YSL, SAINT LAURENT) |
| **Fragrance** | Brand + name + concentration. Each concentration is its own fragrance. | Dior Sauvage EDT (Sauvage EDP is a separate fragrance) |
| **Variant** | One size or format of a fragrance, identified by EAN. | Sauvage EDT 100 ml; Sauvage EDT 100 ml tester |
| **Listing** | One supplier's offer for a variant: price and quantity. | Nunu: €62.40, 14 units |

You make decisions about brands and fragrances. Variants and listings are filled in
automatically from supplier data.

## Brand statuses

Every brand has exactly one status. That status decides what the backoffice shows and what
reaches Telegram.

| Status | Shown in Stock | Alerts | Meaning |
|---|---|---|---|
| **Follow** | Yes | New products and restocks, for every fragrance of the brand | "I want the whole brand." |
| **Browse** | Yes | None, except fragrances you follow individually | "I'll look around, don't ping me." |
| **Ignore** | No, hidden everywhere | None | "Never show me this." |
| **New** | Only in Triage | Listed in the digest with buttons to triage it | A brand that hasn't been seen before. |

- Ignore beats everything: an ignored brand's products don't show in Stock, Changes or the digest.
- You can follow single fragrances from a Browse brand. That's how "in this brand I only want
  Aventus" works.
- The first time each supplier runs, every brand it lists arrives as New. That first triage
  is a one-off bulk job in the backoffice.

## Triage

New brands are triaged in two places:

- **Telegram**: the digest lists new brands with **Follow / Browse / Ignore** buttons. One tap
  sets the status.
- **Backoffice → Triage page**: a list of every New brand with bulk actions, for the big
  first-run batch.

**Merge suggestions.** When a new brand looks like a brand you already have, triage asks
"Same as Yves Saint Laurent?". Confirming adds the new spelling as an alias, and every
supplier's listings under that spelling join the existing brand. Suggestions come from three
signals, strongest first:

1. the same EAN listed under both names at different suppliers;
2. similar names (accents and punctuation ignored, initials such as YSL).

EAN manufacturer prefixes were tried and dropped: they identify the licence holder
(Armani, Lancôme and Valentino share one), not the brand.

The Brands page manages aliases by hand too: merging two brands, splitting one apart, renaming.

## Products: decisions about single fragrances (built)

Besides brands, you decide on single fragrances. A fragrance decision wins over its brand's
status:

| Decision | Shown in Stock | Alerts | Example |
|---|---|---|---|
| **Want** (wishlist) | Yes, badged | New, back in stock, cheaper, whatever the brand's status | Memo is Browse, but you want Ithaque |
| **Own** (collection) | Yes, badged | Never | Amouage is followed; you already have Beach Hut |
| **Not interested** | No (only with "Show hidden") | Never | You don't like Outlands |

- A decision covers every size and tester of that fragrance. It can also be limited to one
  concentration, or set to "Any brand".
- A wishlist entry works before any supplier lists the fragrance: the first listing alerts you.
- You make decisions from Stock (Want / Own / Not interested on each row) or on the Products
  page, which has three tabs: Wishlist, Collection, Not interested. Each entry shows where it's
  available now and the best price.
- For now, listings are matched by reading the fragrance name out of the supplier's product
  name ("AMOUAGE BEACH HUT MAN EDP 100 ML" → Beach Hut Man, EDP). Step 2 replaces this with
  Claude parsing.

## Fragrance catalogue (step 2)

Each supplier listing is split into **brand, fragrance name, concentration, size, and whether
it's a tester**, then attached to a fragrance and variant. This is what lets "follow Aventus"
cover 50 ml, 100 ml and testers, including EANs that appear later.

**Following a fragrance:**

- These always alert: a new variant or listing appears; a sold-out listing comes back.
- Options you switch on per fragrance:
  - **Price drop**: alerts on any decrease.
  - **Low stock**: alerts when the quantity falls below a number you set.
- You can optionally narrow a follow to a single size.

Followed brands alert on new products and restocks for all their fragrances. Price-drop and
low-stock alerts are only set per fragrance.

**Fragrance aliases.** If a listing is attached to the wrong fragrance or misread, you fix it in
the backoffice. The correction is remembered, so the same listing text is always attached the
same way from then on.

### How listings get parsed

Claude parses each listing the first time it appears. The result is stored, so a listing is
never parsed twice and normal runs make no Claude calls. It uses the Claude API with prepaid
credit; the API key lives in `.env` and Dokploy like the other secrets.

The big job, a new supplier's whole catalogue, runs on your laptop instead, through Claude Code
on your subscription: a local command parses the catalogue in batches and uploads the results
to the server. The server's API key then only handles the handful of new listings per day, so
the credit lasts a long time even on the most capable model.

## Product types

- **Non-fragrance** (body lotion, shower gel, deodorant, cosmetics) is hidden by default, using
  the parser's classification. A "show hidden" toggle in Stock reveals it.
- **Testers** are shown normally and marked with a Tester badge.
- Gift sets and minis are shown, each with its own badge.

## Several suppliers, one perfume

Listings with the same EAN are grouped into one Stock row:

- the cheapest supplier is shown first, with the other suppliers listed under it;
- alerts say whether the price is the best one available right now;
- the product page shows a **price history** chart per supplier;
- alerts and Stock show the **lowest price ever seen**, e.g. "lowest seen" or "was €X on 3 Oct".

## The digest

- **One message per collection window** (9:00, 12:00, 21:00). It's sent after all suppliers
  have finished that run.
- **Sent only if something changed** since the previous digest. A quiet window sends nothing.
- If a supplier fails, the digest still goes out with what the other suppliers returned, plus a
  ⚠️ line naming the failed supplier.

Sections, in this order:

1. **⭐ Followed**: new listings, restocks, price drops and low stock for followed brands and
   fragrances, with the best-price and lowest-ever notes.
2. **🆕 New brands to triage**: each brand with Follow / Browse / Ignore buttons and any merge
   suggestion.

Products from Browse brands never appear in the digest. You see them in the backoffice.

## Backoffice pages

- **Changes**: what moved, without hidden brands and fragrances.
- **Stock**: listings from Follow and Browse brands plus fragrances you want or own.
  Filters: brand, supplier, in stock, alerting only, show hidden. Step 2 groups it by
  variant across suppliers.
- **Triage**: New brands, with merge suggestions and bulk actions.
- **Brands**: every brand with its status. A brand's page: rename, merge, spellings, and the
  fragrance decisions made for it.
- **Products**: your fragrance decisions: Wishlist, Collection, Not interested.

The old Rules page is gone: brand watch rules became Follow, brand mute rules became
Browse, EAN and keyword watches became Wishlist entries; other mute rules were dropped.

## Later: your collection

Wishlist and Collection exist already (see Products). Still to come:

- **Purchases**: what you bought, where, when and for how much, shown next to current prices.
- Collection details: bottle size, fill level, where it came from.

## Build order

1. **Brands, triage and digest.** Brand statuses and aliases; the Triage page; merge
   suggestions; Telegram buttons; one digest per window that is sent only when something
   changed. This cuts the noise right away.
2. **Fragrance catalogue.** Claude parsing, fragrances and variants, follows with per-fragrance
   options, non-fragrance hidden, grouping by EAN with the best price.
3. **Price insight.** Price history charts and lowest-ever notes.
4. **Collection.** Purchases and collection details (wishlist and owned are built).

## Technical notes

- Telegram buttons need the bot to receive your taps. Telegram posts each tap to a webhook on
  grasse.xdecade.com. That webhook skips the backoffice password and checks Telegram's secret
  header instead, and it only accepts taps from your chat.
- Sending one digest after all suppliers means a single Dokploy schedule runs every supplier in
  turn and then sends the digest. That schedule replaces the one schedule per supplier.
