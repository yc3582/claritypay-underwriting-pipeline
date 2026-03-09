"""
Web scraper for claritypay.com: fetch -> parse -> validate.

Extracts company-level context (not per-merchant):
- Value propositions (taglines)
- Partner names
- Public stats (merchants served, credit issued, etc.)

Respectful scraping: single request, clear User-Agent, no hammering.
If the site structure changes, the fallback is logged and documented.
"""

import logging
import re

import httpx
from bs4 import BeautifulSoup
from pydantic import ValidationError

from ingestion.validators import ScrapedSiteData

logger = logging.getLogger(__name__)

CLARITYPAY_URL = "https://claritypay.com"
USER_AGENT = "ClarityPay-MLE-TakeHome/1.0 (educational project; single request)"


def fetch_page(url: str = CLARITYPAY_URL) -> str | None:
    """
    Fetch: Download the HTML of claritypay.com.

    Sets a clear User-Agent so the site knows who we are.
    Makes only a single request (respectful scraping).
    """
    logger.info(f"Fetching page: {url}")

    try:
        response = httpx.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=15.0,
            follow_redirects=True,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        logger.warning(f"Site returned error: {e.response.status_code}")
        return None
    except httpx.ConnectError:
        logger.warning(f"Cannot connect to {url}")
        return None
    except httpx.TimeoutException:
        logger.warning(f"Timeout fetching {url}")
        return None

    logger.info(f"Fetched {len(response.text)} chars of HTML")
    return response.text


def parse_page(html: str) -> dict:
    """
    Parse: Extract value propositions, partners, and stats from HTML.

    Uses BeautifulSoup to search the HTML for specific content.
    If the site structure changes, some fields may be empty --
    we log warnings but don't crash.
    """
    soup = BeautifulSoup(html, "html.parser")

    # --- Value propositions ---
    # Look for common heading/tagline patterns
    value_props = []
    # Main hero heading
    for tag in soup.find_all(["h1", "h2"]):
        # separator=" " adds spaces between child elements (e.g. <span>word</span><span>word</span>)
        text = tag.get_text(separator=" ", strip=True)
        if text and len(text) > 10 and len(text) < 200:
            value_props.append(text)

    # If we didn't find enough, also check h3 tags
    if len(value_props) < 3:
        for tag in soup.find_all("h3"):
            text = tag.get_text(separator=" ", strip=True)
            if text and len(text) > 10 and len(text) < 200:
                value_props.append(text)

    # Deduplicate while preserving order
    seen = set()
    unique_props = []
    for p in value_props:
        if p not in seen:
            seen.add(p)
            unique_props.append(p)
    value_props = unique_props

    if not value_props:
        logger.warning("No value propositions found -- site structure may have changed")

    # --- Partner names ---
    # Partners appear near "Proud Partner" text, with logo images
    partners = []
    for tag in soup.find_all(string=lambda s: s and "Proud Partner" in s):
        parent = tag.find_parent()
        if parent:
            # The partner logo image is nearby in the same container
            container = parent.find_parent()
            if container:
                img = container.find("img", alt=True)
                if img and img["alt"].strip():
                    # Alt text is like "Club Wyndham logo" -- strip "logo"
                    name = img["alt"].strip()
                    name = name.replace(" logo", "").replace(" Logo", "").strip()
                    if name:
                        partners.append(name)

    # Deduplicate while preserving order
    partners = list(dict.fromkeys(partners))

    if not partners:
        logger.warning("No partner names found -- site structure may have changed")

    # --- Public stats ---
    # Dynamically discover stats by finding short elements that contain
    # digits + stat symbols (+, %, $, K, B, M), then extracting the
    # nearby label text from sibling elements.
    stats = {}
    for tag in soup.find_all("div"):
        text = tag.get_text(strip=True)

        # Candidate: short text with at least one digit
        if not text or len(text) > 15 or not re.search(r"\d", text):
            continue

        # Must look like a stat value (digits mixed with +, %, $, K, B, M, .)
        if not re.match(r"^[\d$+%KBM.\s]+$", text):
            continue

        # Find the label from sibling elements within the same parent
        parent = tag.parent
        if not parent:
            continue

        label = ""
        for sibling in parent.children:
            if not hasattr(sibling, "get_text"):
                continue
            sib_text = sibling.get_text(strip=True)
            if sib_text and sib_text != text:
                label = sib_text
                break

        if not label:
            continue

        # Convert label to snake_case key
        # e.g. "MerchantsServed*" -> "merchants_served"
        #       "MoM CustomerGrowth*" -> "mom_customer_growth"
        key = re.sub(r"[*]", "", label)                      # strip asterisks
        key = re.sub(r"([a-z])([A-Z])", r"\1_\2", key)       # camelCase -> camel_Case
        key = re.sub(r"[^a-zA-Z0-9]+", "_", key)             # non-alphanumeric -> _
        key = key.strip("_").lower()                          # lowercase, trim edges

        # Deduplicate (site may render stats twice for desktop/mobile)
        if key not in stats:
            stats[key] = text
            logger.debug(f"Discovered stat: {key} = {text}")

    if not stats:
        logger.warning("No stats found -- site structure may have changed")

    return {
        "url": CLARITYPAY_URL,
        "value_propositions": value_props,
        "partners": partners,
        "stats": stats,
    }


def validate_scraped_data(parsed: dict) -> ScrapedSiteData | None:
    """
    Validate: Run parsed data through our Pydantic model.
    """
    try:
        return ScrapedSiteData(**parsed)
    except ValidationError as e:
        logger.warning(f"Scrape validation failed: {e}")
        return None


def ingest_scrape() -> ScrapedSiteData | None:
    """
    Main entry point: fetch -> parse -> validate.

    If scraping fails entirely, returns None with a logged warning.
    The pipeline can still continue without scrape data --
    it's company-level context, not per-merchant data.
    """
    html = fetch_page()
    if html is None:
        logger.warning(
            "Scrape failed. Fallback: pipeline continues without company context. "
            "If this persists, check if claritypay.com is accessible and if the "
            "site structure has changed."
        )
        return None

    parsed = parse_page(html)
    return validate_scraped_data(parsed)
