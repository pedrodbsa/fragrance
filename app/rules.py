"""Watch and mute rules, edited in the backoffice.

A rule matches a product on one field:
  brand     exact brand name, ignoring case          e.g. "Creed"
  ean       any of the product's EANs                e.g. "3508441001114"
  keyword   text anywhere in the name, ignoring case e.g. "aventus"
  supplier  the supplier key                         e.g. "nunu"
"""

FIELDS = ("brand", "ean", "keyword", "supplier")


def matches(rule, product) -> bool:
    value = rule["value"].strip().lower()
    field = rule["field"]
    if field == "brand":
        return product["brand"].lower() == value
    if field == "ean":
        return value in (product["ean"], product["ean2"], product["ean3"])
    if field == "keyword":
        return value in product["name"].lower()
    if field == "supplier":
        return product["supplier"] == value
    return False


def any_match(rules, product) -> bool:
    return any(matches(rule, product) for rule in rules)
