# Grasse: how it should work

Describes behaviour only. Step 1 of the build order, fragrance decisions, the collection,
size grouping and price history are built; the rest is planned.

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

## Brands: Follow, Browse, or Ignore

| Choice | For | Shown in Stock | Alerts |
|---|---|---|---|
| **Follow** | brands you collect (Amouage) | Yes | New products and restocks of every fragrance of the brand |
| **Browse** (the default) | brands worth looking at, without alerts | Yes | Never |
| **Ignore** | brands you'll never want | No (only with Stock's "All brands") | Never |

## Fragrances: your lists

Buying from the wishlist is the main goal. Suppliers have a minimum order value, so an order
is often topped up with fragrances you don't mind owning: those are the fillers.

| List | Shown in Stock | Alerts |
|---|---|---|
| **Wishlist** | Yes | New listings, back in stock, cheaper, whatever the brand's status |
| **Filler** | Yes | Never, even if the brand is followed |
| **Ignore** | No (only with Stock's "All brands") | Never |
| No list | Yes | The brand's status applies |

- A fragrance's list wins over its brand: leave Memo alone but wishlist Ithaque; follow
  Amouage but ignore Outlands or mark Mandarino di Sicilia as a filler.
- The wishlist works before any supplier lists a fragrance: the first listing alerts you.
- Separately, **In collection** marks fragrances you own. It doesn't change alerts: own Beach
  Hut and also ignore it, or own it and keep it on the wishlist to catch a deal.
- Clicking the highlighted choice again takes the fragrance off that list.

## Orders and suppliers

**Suppliers page**: each supplier with whether collecting it works (working, failing with the
error, or no update in 24 hours), when it last worked, how much it has in stock, and its
minimum order value (MOV), entered on the same basis as its prices.

**Baskets**: one open basket per supplier, on the Orders page, filled as you find things
until you place the order. Add a listing (that supplier's size) with "+ Basket" on a product
page, or tick suggestions below and add them. Each item shows its price now ("was €X" if it
changed since you added it) and how many bottles you want ("only N left" when the supplier
has fewer). Items that sell out stay, greyed and left out of the total, which is shown
against the supplier's MOV. The digest tells you when a basket item sells out, comes back or
changes price. "Ordered: empty the basket" starts it again.

**Order suggestions** (Orders page, under the baskets): for each supplier with wishlist
fragrances in stock, an order you could place:

1. every wishlist fragrance it has, one bottle each, in the size you picked on the fragrance's
   page ("Size I'd buy"), or the cheapest size if you didn't pick one;
2. if that's under the MOV, the fillers it has in stock that reach the MOV with the least
   money spent over it. If all its fillers together don't reach it, the page says how short.

Ticking and unticking lines recomputes the total, to try other baskets; the ticked lines
can then go into the supplier's basket.

Suggestions aren't sent to Telegram: the digest is only for what needs your attention
(baskets, the wishlist, followed brands, new brands).

## New brands

Every new brand starts on Browse (shown, no alerts), so nothing urgently needs triage.

- **Telegram**: the digest mentions new brands with **Follow / Ignore** buttons. Not tapping
  keeps Browse.
- **Brands page, New tab**: brands you haven't chosen for yet, newest first, with merge
  suggestions. Tick them and choose Follow, Browse or Ignore in bulk; choosing Browse
  counts too, and takes the brand out of the tab.
- A supplier's first run adds its brands quietly; they appear in the New tab.

**Same name, same brand.** A spelling seen for the first time joins the brand with the same
name, ignoring capitals, accents, punctuation and words like "Parfums", "Perfumes" or "Paris":
"Hermès" joins HERMES, "Orlov Paris" joins Orlov. If two brands share that name it's unclear
which, so it becomes a new brand instead, with a suggestion.

**Merge suggestions.** When a new brand looks like a brand you already have, the New tab and
the digest ask
"Same as Yves Saint Laurent?". Confirming adds the new spelling as an alias, and every
supplier's listings under that spelling join the existing brand. Suggestions come from three
signals, strongest first:

1. the same EAN listed under both names at different suppliers;
2. similar names (accents and punctuation ignored, initials such as YSL).

EAN manufacturer prefixes were tried and dropped: they identify the licence holder
(Armani, Lancôme and Valentino share one), not the brand.

The Brands page manages aliases by hand too: merging two brands, splitting one apart, renaming.
A brand nothing is in stock from can be deleted on its page, with its fragrances and sold-out
listings; one with stock can't (the next sync would bring it back), so ignore it instead.
You can also add a brand yourself (Brands page, "Add a brand"), to follow or ignore it before
any supplier lists it. If you have it already under another spelling, that brand gets the
status instead. A supplier listing it later under the same name lands on it; under another
spelling it shows in the New tab with a "Same as" suggestion.

## Products page

Your fragrance lists in four tabs: **Wishlist**, **Fillers**, **Collection**, **Ignored**. Each entry
shows where it's in stock now and the best price, and opens its product page (every size,
supplier and price history). Add a fragrance by hand there, or use the switches on any Stock
row or product page.

**One juice, many listings.** A fragrance is the juice, whatever the size, batch or EAN. When
the same juice shows up under two names (a supplier's spelling, a batch with its own EAN),
merge them on its product page ("Same juice, other listings"): pick the other name, or accept
a "shares an EAN" hint. Merges are remembered for every supplier and can be split off again.
EANs never merge anything on their own: Nunu reuses some EANs for different fragrances
(Carios and Delina share one).

**Who it's for.** Each fragrance is marked Men, Women or Unisex when a supplier says: the
wholesale shops' catalogue has a field for it, and Nunu's names sometimes do ("… MAN EDP",
"POUR HOMME", "FOR HER"). The first supplier to say wins; correct it on the product page. Stock
filters by it. Fragrances only Nunu lists are mostly unknown until step 2's parsing.

**EANs.** The product page lists every EAN of the fragrance (which supplier and size has it)
and lets you add more. A listing with an EAN you added belongs to that fragrance, whatever its
name says: listings already there move over, and new ones land there from then on. Removing an
added EAN stops that; listings already attached stay. When an EAN on the page belongs to a different
product ("Not this fragrance?"), move it to another of the brand's fragrances or to a new one
you name: its listings go there, and later ones with that EAN land there too.

**Merges page.** Every pair of fragrances of the same brand that shares an EAN, for triage:
same name with a different concentration first (usually suppliers disagreeing about the
label), then different names (spelling variants, but also flankers such as Phantom and
Phantom Night). Per pair: merge, keeping either name, or **Not the same**, which is
remembered so the pair isn't suggested again, there or on the product page.

**Correcting a supplier.** When a supplier gets the name or concentration wrong (Nunu lists
Outrageous as EDP; it's only an EDT), correct it on the product page. If the corrected
fragrance exists already, the two merge. The supplier's wrong version stays linked to the
corrected fragrance, so its listings, including new sizes later, land there too.
The same goes for a fragrance a supplier filed under the wrong brand: move it to the right
brand there (it merges if that brand has it already). When a whole supplier spelling belongs
to another brand, fix it on the brand's page instead (merge, or split the spelling off).

Every listing points to a fragrance in the catalogue. It's worked out once, when the listing
first appears, by reading the name out of the supplier's product name ("AMOUAGE BEACH HUT MAN
EDP 100 ML" → Beach Hut Man, EDP). Every fragrance has its own page, on a list or not. Step 2
replaces the reading with Claude parsing, which then only has to fill in that one link.

## Fragrance catalogue (step 2)

Each supplier listing is split into **brand, fragrance name, concentration, size, and whether
it's a tester**, then attached to a fragrance and variant. This is what lets "Aventus on the wishlist"
cover 50 ml, 100 ml and testers, including EANs that appear later.

**A wishlist fragrance:**

- These always alert: a new variant or listing appears; a sold-out listing comes back.
- Options you switch on per fragrance:
  - **Price drop**: alerts on any decrease.
  - **Low stock**: alerts when the quantity falls below a number you set.
- You can optionally narrow it to a single size.

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
  the parser's classification. Stock's "All brands" choice reveals it.
- **Testers** are shown normally and marked with a Tester badge.
- Gift sets and minis are shown, each with its own badge.

## Several suppliers, one perfume

Listings with the same EAN are grouped into one Stock row:

- the cheapest supplier is shown first, with the other suppliers listed under it;
- alerts say whether the price is the best one available right now;
- the product page shows a **price history** chart per supplier;
- alerts and Stock show the **lowest price ever seen**, e.g. "lowest seen" or "was €X on 3 Oct".

- on the product page and the Orders page (baskets and suggestions), the listing with the
  lowest price in stock for its size is marked **Cheapest** (in green), when at least two
  suppliers have that size in stock.

## The digest

- **One message per collection window** (9:00, 12:00, 21:00). It's sent after all suppliers
  have finished that run.
- **Sent only if something changed** since the previous digest. A quiet window sends nothing.
- If a supplier fails, the digest still goes out with what the other suppliers returned, plus a
  ⚠️ line naming the failed supplier.

Sections, in this order:

1. **🧺 Baskets**: basket items that sold out, came back, or changed price (up or down).
2. **⭐ Followed**: new listings, restocks, price drops and low stock for followed brands and
   wishlist fragrances, with the best-price and lowest-ever notes.
3. **🆕 New brands**: each brand with Follow / Ignore buttons and any merge suggestion.

Brands on default, fillers and fragrances on no list never appear in the digest. You see them in the backoffice.

A price change is recorded only when the price is more than €5 away from the last recorded
price (or the price when first seen). Small daily moves add up: five €1.10 drops make one
"€X → €X−5.50" change. Repricings by a few cents never show. Stock always shows today's price.

## Backoffice pages

- **Changes**: what moved, without hidden brands and fragrances (wishlist fragrances of
  ignored brands are shown). Filters: type of change (including "New or back in stock"), supplier, and all brands or
  following brands only. The Suppliers page links to each supplier's changes, price drops and arrivals.
- **Stock**: one row per fragrance (brand + name + concentration) with its sizes and testers
  and the cheapest price for each, leaving out what you ignored. Filters: brand, supplier, which brands (following; following and Browse; all, ignored too), men / women / unisex, in stock, alerting only, cheapest only (sizes no other supplier sells for less; with a supplier picked, where that supplier is cheapest). Grouping uses the
  fragrance name read from listings, not EANs, so different EANs per size don't matter.
- **Product page**: every listing of one fragrance by size, and a price history chart (one
  line per size and supplier, rebuilt from recorded price changes).
- **Brands**: every brand with its status, bulk Follow / Browse / Ignore, and a New tab for
  brands you haven't chosen for yet (with merge suggestions). A brand's page: rename, merge,
  spellings, and the fragrance decisions made for it.
- **Products**: your fragrance lists: Wishlist, Fillers, Collection, Ignored.
- **Merges**: fragrances that might be the same juice, to merge or mark as different.
- **Search** (box in the header, on every page): brands and fragrances whose names contain
  every word typed ("ysl libre", any spelling of the brand), or the fragrance with an EAN or SKU.
  Accents, capitals, punctuation and spaces are ignored ("lancome", "lhomme", "no5"), in the
  Stock and Brands search boxes too.
- **Orders**: your basket at each supplier, and the order you could place there.
- **Suppliers**: collection health and minimum order values.

Tables sort by clicking a column header (again to reverse). Stock does the same across all
its fragrances (by name, brand, price, quantity), shown in pages of 200 with Previous / Next.

The old Rules page is gone: brand watch rules became Follow, EAN and keyword watches went on
the wishlist; mute and supplier rules were dropped (default covers them).

## Later: your collection

The wishlist, fillers and collection exist already (see Products). Still to come:

- **Purchases**: what you bought, where, when and for how much, shown next to current prices.
- Collection details: bottle size, fill level, where it came from.

## Build order

1. **Brands and digest.** Follow / Ignore and aliases; the New tab; merge
   suggestions; Telegram buttons; one digest per window that is sent only when something
   changed. This cuts the noise right away.
2. **Fragrance catalogue.** Claude parsing, fragrances and variants, follows with per-fragrance
   options, non-fragrance hidden, grouping by EAN with the best price.
3. **Price insight.** Price history chart and lowest price seen on product pages (built);
   lowest-ever notes in alerts still to do.
4. **Collection.** Purchases and collection details (the collection itself is built).

## Technical notes

- Telegram buttons need the bot to receive your taps. Telegram posts each tap to a webhook on
  grasse.xdecade.com. That webhook skips the backoffice password and checks Telegram's secret
  header instead, and it only accepts taps from your chat.
- Sending one digest after all suppliers means a single Dokploy schedule runs every supplier in
  turn and then sends the digest. That schedule replaces the one schedule per supplier.
