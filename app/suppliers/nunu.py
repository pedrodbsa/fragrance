"""Nunu Trading (nunutrading.com), a BigCommerce shop.

The "download stock" button on /stock-offer/ builds its Excel in the browser from the shop's
GraphQL API. We call that API directly: read the API token embedded in the page, log in as
the B2B customer (prices are null otherwise), then page through the perfume category.
Env: NUNU_EMAIL, NUNU_PASSWORD.

Requests go through the curl command, not Python's HTTP client: the shop's Cloudflare blocks
Python clients from server IPs but lets curl through (found 2026-11-11). Stopgap until Nunu
allowlists the server's IP; then this can go back to httpx.
"""

import json
import os
import re
import subprocess
import tempfile

from app.item import Item

BASE = "https://www.nunutrading.com"
PERFUME_CATEGORY = 37
PAGE_SIZE = 50

LOGIN = """
mutation($email: String!, $password: String!) {
  login(email: $email, password: $password) { result }
}"""

PRODUCTS = """
query($after: String, $category: Int!, $first: Int!) {
  site { search { searchProducts(
      filters: { categoryEntityIds: [$category], hideOutOfStock: true }
      sort: A_TO_Z
  ) { products(first: $first, after: $after) {
        pageInfo { endCursor hasNextPage }
        edges { node {
          sku name upc
          brand { name }
          prices { price { value } }
          inventory { aggregated { availableToSell } }
          customFields { edges { node { name value } } }
        } }
  } } } }
}"""


def fetch() -> list[Item]:
    with tempfile.NamedTemporaryFile() as cookies:  # holds the login session between requests
        def curl(path, *args, body=None):
            # The body goes in on stdin, so the password never appears in the process list.
            done = subprocess.run(
                ["curl", "-sS", "--fail-with-body", "--compressed", "--max-time", "60",
                 "-b", cookies.name, "-c", cookies.name, *args, BASE + path],
                input=body, capture_output=True, text=True,
            )
            if done.returncode != 0:
                raise RuntimeError(f"Nunu request {path} failed: {done.stderr.strip()} {done.stdout[:300]}")
            return done.stdout

        page = curl("/stock-offer/")
        token = re.search(r"storefrontApiToken = '([^']+)'", page).group(1)

        def gql(query, variables):
            body = json.loads(curl(
                "/graphql", "--data-binary", "@-",
                "-H", "Content-Type: application/json",
                "-H", f"Authorization: Bearer {token}",
                "-H", f"Origin: {BASE}",
                body=json.dumps({"query": query, "variables": variables}),
            ))
            if body.get("errors"):
                raise RuntimeError(f"Nunu GraphQL error: {body['errors']}")
            return body["data"]

        login = gql(LOGIN, {"email": os.environ["NUNU_EMAIL"], "password": os.environ["NUNU_PASSWORD"]})
        if login["login"]["result"] != "success":
            raise RuntimeError(f"Nunu login failed: {login}")

        items, cursor, more = [], None, True
        while more:
            data = gql(PRODUCTS, {"after": cursor, "category": PERFUME_CATEGORY, "first": PAGE_SIZE})
            products = data["site"]["search"]["searchProducts"]["products"]
            for edge in products["edges"]:
                node = edge["node"]
                fields = {f["node"]["name"].lower(): f["node"]["value"] for f in node["customFields"]["edges"]}
                items.append(Item(
                    sku=node["sku"],
                    name=node["name"],
                    brand=(node["brand"] or {}).get("name", ""),
                    ean=node["upc"] or None,
                    ean2=fields.get("ean 2"),
                    ean3=fields.get("ean 3"),
                    qty=node["inventory"]["aggregated"]["availableToSell"],
                    # A missing price means the login didn't stick; failing beats recording
                    # thousands of fake price changes.
                    price=node["prices"]["price"]["value"],
                    flagged_new=fields.get("nuevo") == "Si",
                ))
            cursor = products["pageInfo"]["endCursor"]
            more = products["pageInfo"]["hasNextPage"]
        return items
