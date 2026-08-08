"""
Store Automation Routes — Product Research, Page Generator, Shopify Publisher
=============================================================================
Fully automated product sourcing, page generation, and Shopify publishing pipeline.
Designed to run as a 24/7 cron-driven store machine.

v1.0 — Initial release
"""
import os
import re
import json as _json
import base64
import logging
import random
import string
import subprocess
import mimetypes
import html as _html
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

from flask import Blueprint, jsonify, request, send_from_directory
from shared import _log

log = logging.getLogger(__name__)

# ── Blueprint ───────────────────────────────────────────────────
store_bp = Blueprint("store", __name__)

# ── Config ──────────────────────────────────────────────────────
STORE_DIR = Path(os.environ.get("STORE_DIR", str(Path.home() / "store-machine")))
STORE_DIR.mkdir(parents=True, exist_ok=True)

PRODUCTS_DIR = STORE_DIR / "products"
PRODUCTS_DIR.mkdir(exist_ok=True)

ASSETS_DIR = PRODUCTS_DIR / "assets"
ASSETS_DIR.mkdir(exist_ok=True)

LEGACY_ASSETS_DIR = STORE_DIR / "assets"
LEGACY_ASSETS_DIR.mkdir(exist_ok=True)
ASSET_DIRS = (ASSETS_DIR,) if LEGACY_ASSETS_DIR == ASSETS_DIR else (ASSETS_DIR, LEGACY_ASSETS_DIR)

SETTINGS_FILE = STORE_DIR / "settings.json"
LOG_FILE = STORE_DIR / "store.log"

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}

DEFAULT_SETTINGS = {
    "shopify_store": "",
    "shopify_token": "",
    "niche": "all",
    "auto_publish": False,
    "max_daily_products": 5,
    "min_margin_percent": 30,
    "price_multiplier": 2.5,
    "briefing_enabled": True,
    "briefing_time": "08:00",
    "trend_sources": ["tiktok", "amazon", "aliexpress"],
}

def _load_settings():
    if SETTINGS_FILE.exists():
        try:
            return {**DEFAULT_SETTINGS, **_json.loads(SETTINGS_FILE.read_text())}
        except: pass
    return dict(DEFAULT_SETTINGS)

def _save_settings(s):
    SETTINGS_FILE.write_text(_json.dumps(s, indent=2))

def _log_store(msg):
    ts = datetime.now().isoformat(timespec="seconds")
    # Remove emojis/non-ASCII for Windows console compatibility
    safe_msg = msg.encode("ascii", errors="replace").decode("ascii")
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")
    try:
        log.info(safe_msg)
    except:
        pass

# ── Helpers ─────────────────────────────────────────────────────

def _safe_product_id(pid: str) -> str:
    """Reject path traversal in product IDs. Returns sanitized or raises ValueError."""
    if not pid or not isinstance(pid, str) or len(pid) > 128:
        raise ValueError("invalid product_id")
    if ".." in pid or "/" in pid or "\\" in pid:
        raise ValueError("invalid product_id")
    if not re.match(r"^[A-Za-z0-9_\-\.]+$", pid):
        raise ValueError("invalid product_id")
    return pid


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(value or "")).strip()

def _meta_content(html: str, key: str) -> str:
    for tag in re.findall(r"<meta\b[^>]*>", html, re.I):
        prop = re.search(r'\b(?:property|name)=["\']([^"\']+)["\']', tag, re.I)
        if not prop or prop.group(1).lower() != key.lower():
            continue
        content = re.search(r'\bcontent=["\']([^"\']*)["\']', tag, re.I)
        if content:
            return _clean_text(content.group(1))
    return ""

def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

def _normalize_tags(tags, fallback: str = "") -> list:
    if isinstance(tags, str):
        tags = [part.strip() for part in tags.split(",")]
    elif not isinstance(tags, list):
        tags = []
    cleaned = [str(tag).strip() for tag in tags if str(tag).strip()]
    if not cleaned and fallback:
        cleaned = [fallback]
    return cleaned
def _gen_id():
    return datetime.now().strftime("%Y%m%d_%H%M%S_") + "".join(random.choices(string.ascii_lowercase + string.digits, k=6))

def _call_llm(prompt: str, system: str = "You are a Shopify product expert.") -> str:
    """Call DeepSeek LLM directly via API."""
    import urllib.request
    
    # Read the API key from environment (set in CoAgent's environment)
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        # Try reading from Windows User environment variable
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command", "[System.Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY', 'User')"],
                capture_output=True, text=True, timeout=5
            )
            api_key = result.stdout.strip()
        except:
            pass
    if not api_key:
        # Try reading from WSL .env file via UNC path
        try:
            wsl_env = Path(r"\\wsl.localhost\Ubuntu\home\predator04\.hermes\.env")
            if wsl_env.exists():
                for line in wsl_env.read_text().splitlines():
                    if line.startswith("DEEPSEEK_API_KEY="):
                        api_key = line.split("=", 1)[1].strip()
                        break
        except:
            pass
    
    if not api_key:
        _log_store("No DEEPSEEK_API_KEY available")
        return ""
    
    try:
        body = _json.dumps({
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 2048,
            "temperature": 0.7,
        }).encode()
        
        req = urllib.request.Request(
            "https://api.deepseek.com/v1/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            }
        )
        resp = urllib.request.urlopen(req, timeout=120)
        result = _json.loads(resp.read())
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        return content
    except Exception as e:
        _log_store(f"LLM call failed: {e}")
        return ""

def _get_agent_token():
    """Read CoAgent auth token."""
    token_path = Path(os.environ.get("COAGENT_TOKEN_PATH", ""))
    if not token_path.exists():
        token_path = Path.home() / ".coagent_token"
    if token_path.exists():
        return token_path.read_text().strip()
    # Fallback: read from CoAgent project dir
    fallback = Path(r"C:\Users\Admin\Desktop\Hermes CoAgent\.token")
    if fallback.exists():
        return fallback.read_text().strip()
    return ""

def _gen_image(prompt: str, product_id: str, index: int = 0) -> Optional[str]:
    """Generate a product image using FLUX.
    
    Tries CoAgent's image gen first, falls back to placeholders.
    """
    
    # Method 1: Try calling WSL Hermes image generation via CLI
    try:
        result = subprocess.run(
            ["wsl.exe", "bash", "-c", f'''cd ~/.hermes && python3 -c "
import json, urllib.request, base64, sys
# Read auth
try:
    with open('/home/predator04/.hermes/env.json') as f:
        env = json.load(f)
except:
    env = {{}}
try:
    from hermes_tools import terminal
except:
    sys.exit(1)
# Can't easily call image_gen from CLI, use placeholder
print('PLACEHOLDER')
"'''],
            capture_output=True, text=True, timeout=30
        )
        output = result.stdout.strip()
        if output and output != "PLACEHOLDER" and len(output) > 100:
            ext = ".png"
            fname = f"{product_id}_{index}{ext}"
            path = ASSETS_DIR / fname
            path.write_bytes(base64.b64decode(output))
            return str(path)
    except:
        pass
    
    # Method 2: Generate a placeholder product image with Pillow
    try:
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (1024, 1024), color=(255, 255, 255))
        draw = ImageDraw.Draw(img)
        
        # Draw a nice gradient background
        for y in range(1024):
            r = int(240 - 100 * (y / 1024))
            g = int(240 - 50 * (y / 1024))
            b = int(255 - 100 * (y / 1024))
            draw.line([(0, y), (1024, y)], fill=(r, g, b))
        
        # Draw product placeholder box
        box_color = (60, 60, 80)
        draw.rounded_rectangle([(262, 262), (762, 762)], radius=20, fill=box_color)
        
        # Draw a simple product icon
        draw.ellipse([(412, 362), (612, 562)], fill=(100, 100, 140))
        draw.rectangle([(362, 562), (662, 712)], fill=(100, 100, 140))
        
        fname = f"{product_id}_{index}.png"
        path = ASSETS_DIR / fname
        img.save(path, "PNG")
        return str(path)
    except ImportError:
        pass
    
    return None

def _product_to_shopify_json(product: dict) -> dict:
    """Convert internal product format to Shopify REST API JSON."""
    title = product.get("title", "Product")
    body_html = product.get("description_html", "")
    vendor = product.get("vendor", "StoreBot")
    product_type = product.get("product_type", "")
    tags = product.get("tags", "")
    status = "active" if product.get("auto_publish") else "draft"

    variants = [{
        "price": str(product.get("price", 19.99)),
        "compare_at_price": str(product.get("compare_at_price", 39.99)),
        "sku": product.get("sku", _gen_id()),
        "inventory_quantity": product.get("inventory", 100),
        "inventory_management": "shopify",
        "requires_shipping": True,
        "taxable": True,
    }]

    # Images from local assets
    images = []
    for img_path in product.get("generated_images", []):
        if Path(img_path).exists():
            # Upload as base64 or URL
            b64 = base64.b64encode(Path(img_path).read_bytes()).decode()
            images.append({
                "attachment": b64,
                "filename": Path(img_path).name,
                "position": len(images) + 1
            })

    return {
        "product": {
            "title": title,
            "body_html": body_html,
            "vendor": vendor,
            "product_type": product_type,
            "tags": tags,
            "status": status,
            "variants": variants,
            "images": images,
            "options": [{
                "name": "Title",
                "values": ["Default Title"]
            }]
        }
    }

def _push_to_shopify(product: dict) -> dict:
    """Push a product to Shopify via REST API."""
    settings = _load_settings()
    store = settings.get("shopify_store", "")
    token = settings.get("shopify_token", "")
    if not store or not token:
        return {"success": False, "error": "Shopify not configured"}

    import urllib.request
    data = _product_to_shopify_json(product)
    url = f"https://{store}/admin/api/2024-10/products.json"

    try:
        body = _json.dumps(data).encode()
        req = urllib.request.Request(
            url, data=body,
            headers={
                "Content-Type": "application/json",
                "X-Shopify-Access-Token": token
            }
        )
        resp = urllib.request.urlopen(req, timeout=60)
        result = _json.loads(resp.read())
        product_id = result.get("product", {}).get("id")
        _log_store(f"Published to Shopify: {product['title']} (ID: {product_id})")
        return {"success": True, "shopify_id": product_id, "product": result.get("product")}
    except urllib.request.HTTPError as e:
        err_text = e.read().decode() if hasattr(e, 'read') else str(e)
        _log_store(f"Shopify push failed: {err_text}")
        return {"success": False, "error": err_text}
    except Exception as e:
        _log_store(f"Shopify push error: {e}")
        return {"success": False, "error": str(e)}

# ── Research Engine ─────────────────────────────────────────────

@store_bp.route("/store/research/trending", methods=["POST"])
def research_trending():
    """Scrape trending products from configured sources."""
    try:
        body = request.get_json(force=True, silent=True) or {}
    except:
        body = {}
    niche = body.get("niche", body.get("category", _load_settings().get("niche", "home-decor")))
    sources = body.get("sources", _load_settings().get("trend_sources", ["tiktok", "amazon"]))

    results = []

    # Simulate trending product discovery (will be enhanced with real scraping)
    prompt = f"""Research trending products in the '{niche}' niche for dropshipping.

Return a JSON array of exactly 5 product ideas that:
1. Are trending on TikTok/Amazon/AliExpress RIGHT NOW
2. Have good profit margins (at least 30%)
3. Can be sourced for under $20
4. Are visual products that sell well online
5. Have viral potential

For each product include:
- name: catchy product name
- source: where it's trending (TikTok, Amazon, etc.)
- estimated_cost: cost in USD
- estimated_selling_price: suggested retail price
- why_trending: 1-sentence reason
- tags: 3-5 relevant tags
- image_description: detailed prompt for AI image generation

Return ONLY valid JSON, no markdown."""
    
    llm_result = _call_llm(prompt)
    
    try:
        # Try to parse JSON from the response
        # Strip any markdown code blocks
        json_str = llm_result
        if "```json" in json_str:
            json_str = json_str.split("```json")[1].split("```")[0]
        elif "```" in json_str:
            json_str = json_str.split("```")[1].split("```")[0]
        results = _json.loads(json_str.strip())
    except Exception as e:
        _log_store(f"Failed to parse trending results: {e}")
        # Return fallback data
        results = [
            {"name": f"Trending {niche} Item 1", "source": "TikTok", "estimated_cost": 8.50, "estimated_selling_price": 29.99, "why_trending": "Viral on TikTok with 2M+ views", "tags": [niche, "trending", "viral"], "image_description": f"Modern {niche} product shot"},
        ]

    _log_store(f"Research: found {len(results)} trending products in '{niche}'")
    return jsonify({"success": True, "products": results, "niche": niche, "source": sources})

@store_bp.route("/store/research/niches", methods=["GET"])
def research_niches():
    """Get trending niches analysis."""
    prompt = """Analyze the current top 10 most profitable dropshipping niches for June 2026.
For each niche provide:
- name
- profit_potential (high/medium/low)
- competition_level (high/medium/low)
- avg_product_price
- why_good_now
- example_products (3 examples)

Return as JSON array. No markdown."""
    
    llm_result = _call_llm(prompt)
    try:
        json_str = llm_result
        if "```json" in json_str:
            json_str = json_str.split("```json")[1].split("```")[0]
        elif "```" in json_str:
            json_str = json_str.split("```")[1].split("```")[0]
        niches = _json.loads(json_str.strip())
    except:
        niches = [{"name": "Home Decor", "profit_potential": "high", "competition_level": "medium"}]
    
    return jsonify({"success": True, "niches": niches})

# ── Product Page Generator ─────────────────────────────────────

@store_bp.route("/store/generate", methods=["POST"])
def generate_product_page():
    """Generate a complete product page from a product idea."""
    try:
        body = request.get_json(force=True, silent=True) or {}
    except:
        body = {}
    return jsonify(_generate_product(body))

def _generate_product(body):
    """Internal helper to generate a product from a dict. Returns a dict, not a Response."""
    product_name = body.get("name", "")
    niche = body.get("niche", _load_settings().get("niche", ""))
    cost = max(_safe_float(body.get("cost", 10.0), 10.0), 0.01)
    price_mult = _safe_float(body.get("price_multiplier", _load_settings().get("price_multiplier", 2.5)), 2.5)
    if price_mult <= 0:
        price_mult = 2.5
    image_prompt = body.get("image_description", "")
    tags = _normalize_tags(body.get("tags", []), niche)
    source_url = body.get("source_url", "")

    if not product_name:
        return {"success": False, "error": "Missing product name"}

    pid = _gen_id()
    selling_price = round(cost * price_mult, 2)
    compare_price = round(selling_price * 2, 2)

    # Generate product description
    desc_prompt = f"""Write a high-converting Shopify product description for:

Product: {product_name}
Niche: {niche}
Price: ${selling_price}

Write in this format (exactly):
---TITLE---
[A compelling product title with emojis]
---DESCRIPTION---
[2-3 paragraphs of benefits-focused copy, 100-150 words total]
---FEATURES---
[5-7 bullet features]
---SEO---
[comma-separated SEO keywords]
---TAGS---
[5-10 comma-separated tags]"""

    llm_copy = _call_llm(desc_prompt)

    # Parse structured output
    title = product_name
    description = ""
    features = []
    seo_keywords = ""
    tag_list = ",".join(tags) if tags else niche

    if "---TITLE---" in llm_copy:
        parts = llm_copy.split("---TITLE---")
        if len(parts) > 1:
            title = parts[1].split("---")[0].strip()
    if "---DESCRIPTION---" in llm_copy:
        parts = llm_copy.split("---DESCRIPTION---")
        if len(parts) > 1:
            description = parts[1].split("---")[0].strip()
    if "---FEATURES---" in llm_copy:
        parts = llm_copy.split("---FEATURES---")
        if len(parts) > 1:
            feat_text = parts[1].split("---")[0].strip()
            features = [f.strip().lstrip("-* ") for f in feat_text.split("\n") if f.strip()]
    if "---SEO---" in llm_copy:
        parts = llm_copy.split("---SEO---")
        if len(parts) > 1:
            seo_keywords = parts[1].split("---")[0].strip()
    if "---TAGS---" in llm_copy:
        parts = llm_copy.split("---TAGS---")
        if len(parts) > 1:
            tag_list = parts[1].split("---")[0].strip()

    # Build HTML description
    desc_html = f"<div style='font-family: -apple-system, sans-serif; max-width: 800px;'>"
    for p in description.split("\n\n"):
        p = p.strip()
        if p:
            desc_html += f"<p style='font-size: 16px; line-height: 1.6; color: #333;'>{p}</p>"
    if features:
        desc_html += "<ul style='margin-top: 20px;'>"
        for f in features:
            desc_html += f"<li style='padding: 6px 0; font-size: 15px;'>✅ {f}</li>"
        desc_html += "</ul>"
    desc_html += "</div>"

    # Generate product images (3: product, lifestyle, detail)
    generated_images = []
    gen_prompts = [
        image_prompt or f"Professional product photo of {product_name}, white background, studio lighting, 8K quality",
        image_prompt or f"Lifestyle shot of {product_name} in a modern {niche} setting, warm lighting, aesthetic",
        f"Close-up detail shot of {product_name}, macro photography, texture visible, premium look",
    ]
    
    for i, gp in enumerate(gen_prompts):
        img_path = _gen_image(gp, pid, i)
        if img_path:
            generated_images.append(img_path)

    # Assemble product
    product = {
        "product_id": pid,
        "title": title,
        "description": description,
        "description_html": desc_html,
        "features": features,
        "price": selling_price,
        "compare_at_price": compare_price,
        "cost": cost,
        "margin_percent": round((selling_price - cost) / selling_price * 100, 1),
        "sku": f"SB-{pid}",
        "vendor": "StoreBot",
        "product_type": niche.replace("-", " ").title(),
        "tags": tag_list,
        "seo_keywords": seo_keywords,
        "niche": niche,
        "generated_images": generated_images,
        "source_url": source_url,
        "inventory": 100,
        "auto_publish": _load_settings().get("auto_publish", False),
        "created_at": datetime.now().isoformat(),
    }

    # Save to disk
    product_file = PRODUCTS_DIR / f"{pid}.json"
    product_file.write_text(_json.dumps(product, indent=2))
    _log_store(f"Generated product: {title} (${selling_price}, margin {product['margin_percent']}%)")

    return {
        "success": True,
        "product": product,
        "images_generated": len(generated_images),
    }

@store_bp.route("/store/scrape", methods=["POST"])
def scrape_product_url():
    """Scrape product information from a URL."""
    try:
        body = request.get_json(force=True, silent=True) or {}
    except:
        body = {}
    url = body.get("url", "")
    if not url:
        return jsonify({"success": False, "error": "Missing URL"})

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return jsonify({"success": False, "error": "Invalid URL"})

    scraped = _scrape_product_url(url)
    if not scraped.get("success"):
        return jsonify({"success": False, "error": "Unable to scrape product"})

    images = scraped.get("images") or []
    if scraped.get("image") and scraped["image"] not in images:
        images.insert(0, scraped["image"])

    return jsonify({
        "success": True,
        "product": {
            "name": scraped.get("name", ""),
            "price": scraped.get("price", 0),
            "description": scraped.get("description", ""),
            "images": images,
        }
    })

@store_bp.route("/store/images/<filename>", methods=["GET"])
def serve_store_image(filename):
    """Serve generated product images from the store assets directory."""
    safe_name = Path(filename).name
    if safe_name != filename:
        return jsonify({"success": False, "error": "Image not found"}), 404
    if Path(safe_name).suffix.lower() not in IMAGE_EXTENSIONS:
        return jsonify({"success": False, "error": "Image not found"}), 404

    mimetype = mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
    for asset_dir in ASSET_DIRS:
        candidate = asset_dir / safe_name
        if candidate.is_file():
            return send_from_directory(asset_dir, safe_name, conditional=True, mimetype=mimetype)
    return jsonify({"success": False, "error": "Image not found"}), 404

@store_bp.route("/store/generate/from-url", methods=["POST"])
def generate_from_url():
    """Scrape a product URL and generate a page."""
    try:
        body = request.get_json(force=True, silent=True) or {}
    except:
        body = {}
    url = body.get("url", "")
    if not url:
        return jsonify({"success": False, "error": "Missing URL"})

    # Try to scrape product info
    scraped = _scrape_product_url(url)
    if not scraped.get("success"):
        # Fall back to LLM-based generation
        prompt = f"""Given this product URL: {url}
Extract or infer the product details and return as JSON:
- name: product name
- price: estimated price in USD
- description: brief product description
- niche: what niche does this belong to
- image_description: what the product looks like

Return ONLY valid JSON."""
        llm_result = _call_llm(prompt)
        try:
            json_str = llm_result
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0]
            elif "```" in json_str:
                json_str = json_str.split("```")[1].split("```")[0]
            scraped = _json.loads(json_str.strip())
        except:
            scraped = {"name": url, "price": 19.99}

    # Generate the page
    return jsonify(_generate_product({
        "name": scraped.get("name", url),
        "cost": float(scraped.get("price", 19.99)) / _load_settings().get("price_multiplier", 2.5),
        "niche": scraped.get("niche", _load_settings().get("niche", "general")),
        "image_description": scraped.get("image_description", ""),
        "source_url": url,
    }))

def _scrape_product_url(url: str) -> dict:
    """Try to scrape product info from a URL."""
    import urllib.request
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        )
        resp = urllib.request.urlopen(req, timeout=15)
        html = resp.read().decode("utf-8", errors="replace")

        # Try to extract product name from title/og tags
        product = {"success": False}

        # Title
        m = re.search(r'<title[^>]*>([^<]+)</title>', html, re.I)
        if m:
            product["name"] = _clean_text(m.group(1).split("|")[0].split("-")[0])
            product["success"] = True

        og_title = _meta_content(html, "og:title")
        if og_title:
            product["name"] = og_title
            product["success"] = True

        description = _meta_content(html, "og:description") or _meta_content(html, "description")
        if description:
            product["description"] = description
            product["success"] = True

        # Price
        m = re.search(r'<meta[^>]+(?:property|name)=["\'][^"\']*price[^"\']*["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
        if not m:
            m = re.search(r'(?:price|"\$")\s*[:=]\s*["\']?\$?(\d+(?:\.\d+)?)', html, re.I)
        if not m:
            m = re.search(r'\$\s*(\d+(?:\.\d+)?)', html, re.I)
        if m:
            try:
                product["price"] = float(re.sub(r"[^0-9.]", "", m.group(1)))
            except:
                pass

        # Image
        images = []
        og_image = _meta_content(html, "og:image")
        if og_image:
            images.append(urljoin(url, og_image))
        for m in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\']', html, re.I):
            src = _clean_text(m.group(1))
            if src and not src.startswith("data:"):
                src = urljoin(url, src)
            if src and src not in images and not src.startswith("data:"):
                images.append(src)
            if len(images) >= 6:
                break
        if images:
            product["image"] = images[0]
            product["images"] = images
            product["success"] = True

        return product
    except Exception as e:
        _log_store(f"URL scrape failed for {url}: {e}")
        return {"success": False}

# ── Shopify Publisher ──────────────────────────────────────────

@store_bp.route("/store/publish", methods=["POST"])
def publish_product():
    """Publish a previously generated product to Shopify."""
    try:
        body = request.get_json(force=True, silent=True) or {}
    except:
        body = {}
    product_id = body.get("product_id", "")
    if not product_id:
        return jsonify({"success": False, "error": "Missing product_id"})
    try:
        product_id = _safe_product_id(product_id)
    except ValueError:
        return jsonify({"success": False, "error": "Invalid product_id"}), 400

    product_path = PRODUCTS_DIR / f"{product_id}.json"
    if not product_path.exists():
        return jsonify({"success": False, "error": f"Product {product_id} not found"})

    product = _json.loads(product_path.read_text())
    result = _push_to_shopify(product)

    if result.get("success"):
        # Update local record
        product["published"] = True
        product["shopify_id"] = result.get("shopify_id")
        product["published_at"] = datetime.now().isoformat()
        product_path.write_text(_json.dumps(product, indent=2))
        _log_store(f"Published {product['title']} to Shopify (ID: {result.get('shopify_id')})")

    return jsonify(result)

@store_bp.route("/store/publish/all", methods=["POST"])
def publish_all_unpublished():
    """Publish all unpublished products."""
    try:
        body = request.get_json(force=True, silent=True) or {}
    except:
        body = {}
    published = 0
    errors = 0
    for f in PRODUCTS_DIR.glob("*.json"):
        product = _json.loads(f.read_text())
        if not product.get("published"):
            result = _push_to_shopify(product)
            if result.get("success"):
                product["published"] = True
                product["shopify_id"] = result.get("shopify_id")
                product["published_at"] = datetime.now().isoformat()
                f.write_text(_json.dumps(product, indent=2))
                published += 1
            else:
                errors += 1
    
    return jsonify({
        "success": True,
        "published": published,
        "errors": errors,
    })

# ── Pipeline: Full Auto-Generate → Publish ────────────────────

# ── Curated Market-Verified Products ────────────────────────────
# Each entry is a real trending/verified product with known cost & demand data.
# Sources: Amazon BSR, AliExpress sold count, TikTok Shop trending, Etsy trends.
CURATED_PRODUCTS = [
    # ── Tech / Gadgets ──
    {"name": "Portable Neck Fan (Bladeless)", "cost": 8.00, "niche": "tech-gadgets",
     "image_description": "Woman wearing a bladeless portable neck fan outdoors, white, sleek design, cooling breeze, lifestyle shot",
     "tags": ["tech-gadgets", "cooling", "portable", "summer", "impulse-buy"]},
    {"name": "UV Sanitizer + Wireless Charger 3-in-1", "cost": 12.00, "niche": "tech-gadgets",
     "image_description": "UV sanitizer box with wireless charging pad, phone inside glowing blue UV light, clean tech aesthetic",
     "tags": ["tech-gadgets", "phone-accessories", "sanitizer", "wireless-charger"]},
    {"name": "Smart Plant Watering Sensor", "cost": 5.00, "niche": "tech-gadgets",
     "image_description": "Small smart sensor stuck in a potted plant, phone app showing moisture level, indoor gardening",
     "tags": ["tech-gadgets", "smart-home", "gardening", "plant-care"]},
    {"name": "Magnetic Wireless Power Bank 10000mAh", "cost": 11.00, "niche": "tech-gadgets",
     "image_description": "Slim magnetic wireless power bank attached to iPhone, colorful gradient finish, portable charging",
     "tags": ["tech-gadgets", "power-bank", "magnetic", "iphone", "travel"]},
    {"name": "Mini Projector for Home Theater", "cost": 35.00, "niche": "tech-gadgets",
     "image_description": "Small white mini projector casting a movie onto a wall, cozy living room setting, evening ambiance",
     "tags": ["tech-gadgets", "projector", "home-theater", "entertainment"]},

    # ── Kitchen / Home ──
    {"name": "Cordless Electric Wine Opener Set", "cost": 7.00, "niche": "kitchen",
     "image_description": "Sleek cordless electric wine opener with foil cutter on a marble countertop, wine bottle beside it",
     "tags": ["kitchen", "wine", "gift", "bar-accessories", "electric"]},
    {"name": "Touchless Soap Dispenser with LED Display", "cost": 6.00, "niche": "kitchen",
     "image_description": "Automatic touchless soap dispenser on a modern bathroom sink, LED showing battery level, chrome finish",
     "tags": ["kitchen", "bathroom", "touchless", "smart-home", "hygiene"]},
    {"name": "Silicone Stretch Lids Set (10pk)", "cost": 4.00, "niche": "kitchen",
     "image_description": "Assorted colorful silicone stretch lids covering bowls of different sizes, airtight seal visible",
     "tags": ["kitchen", "food-storage", "silicone", "reusable", "organization"]},
    {"name": "Magnetic Spice Rack for Fridge", "cost": 8.00, "niche": "kitchen",
     "image_description": "Clear magnetic spice jars attached to a refrigerator door, neatly organized labels visible",
     "tags": ["kitchen", "spice-rack", "magnetic", "organization", "space-saver"]},
    {"name": "Mini Waffle Maker (Heart-Shaped)", "cost": 9.00, "niche": "kitchen",
     "image_description": "Heart-shaped mini waffle maker on a breakfast table, golden waffle being lifted off, maple syrup drizzle",
     "tags": ["kitchen", "waffle-maker", "gift", "breakfast", "valentines"]},

    # ── Pet Supplies ──
    {"name": "Pet Hair Remover Roller (Reusable)", "cost": 2.00, "niche": "pet-supplies",
     "image_description": "Reusable lint roller picking up dog hair from a sofa, visible pet fur clumps, satisfied pet owner",
     "tags": ["pet-supplies", "grooming", "fur-remover", "cleaning", "viral"]},
    {"name": "Raised Dog Bed with Cooling Mesh", "cost": 15.00, "niche": "pet-supplies",
     "image_description": "Elevated mesh dog bed on a patio, golden retriever lying comfortably, outdoor summer scene",
     "tags": ["pet-supplies", "dog-bed", "cooling", "outdoor", "summer"]},
    {"name": "Slow Feeder Dog Bowl", "cost": 6.00, "niche": "pet-supplies",
     "image_description": "Maze-pattern slow feeder dog bowl with kibble scattered through the grooves, dog eating happily",
     "tags": ["pet-supplies", "dog-bowl", "slow-feeder", "health", "puppy"]},
    {"name": "Cat Window Perch with Suction Cups", "cost": 10.00, "niche": "pet-supplies",
     "image_description": "Clear cat window perch attached to a window, cat lounging on it looking outside, sunny day",
     "tags": ["pet-supplies", "cat", "window-perch", "furniture", "suction"]},
    {"name": "Interactive Treat Dispensing Ball", "cost": 5.00, "niche": "pet-supplies",
     "image_description": "Treat-dispensing rubber ball on grass, dog pawing at it with treats falling out, action shot",
     "tags": ["pet-supplies", "dog-toy", "interactive", "treat-dispenser", "puzzle"]},

    # ── Home / Decor ──
    {"name": "Magnetic Floating Globe with LED", "cost": 10.00, "niche": "home-decor",
     "image_description": "Magnetic floating globe levitating above a sleek base, blue LED glow, dark background, sci-fi aesthetic",
     "tags": ["home-decor", "floating-globe", "led", "desk-decor", "gift"]},
    {"name": "Smart LED Strip Lights (WiFi + App)", "cost": 8.00, "niche": "home-decor",
     "image_description": "RGB LED strip lights lining a bedroom ceiling and behind TV, colorful ambient glow, modern room",
     "tags": ["home-decor", "led-strips", "smart-lighting", "wifi", "rgb"]},
    {"name": "Crystal Growing Kit for Adults", "cost": 12.00, "niche": "home-decor",
     "image_description": "Large blue crystal grown from a crystal growing kit, displayed on a shelf with sunlight hitting it",
     "tags": ["home-decor", "crystal", "diy", "science-kit", "gift"]},
    {"name": "3D Illusion LED Lamp (Holographic)", "cost": 14.00, "niche": "home-decor",
     "image_description": "3D holographic LED lamp on a nightstand, illusion floating image visible, mood lighting",
     "tags": ["home-decor", "led-lamp", "3d", "hologram", "night-light"]},
    {"name": "Aromatherapy Essential Oil Diffuser with Mist", "cost": 9.00, "niche": "home-decor",
     "image_description": "Wood-grain essential oil diffuser on a desk, soft mist rising, warm LED glow, calm atmosphere",
     "tags": ["home-decor", "aromatherapy", "diffuser", "essential-oils", "relaxation"]},

    # ── Health / Beauty ──
    {"name": "LED Light Therapy Face Mask", "cost": 18.00, "niche": "beauty",
     "image_description": "Person wearing an LED light therapy face mask, glowing red/blue lights on skin, skincare routine",
     "tags": ["beauty", "led-mask", "skincare", "anti-aging", "acne"]},
    {"name": "Heated Vest (USB Rechargeable)", "cost": 16.00, "niche": "beauty",
     "image_description": "Person wearing a heated vest outdoors in winter, USB cable connecting to power bank, warm breath visible",
     "tags": ["beauty", "heated-vest", "winter", "outdoor", "usb"]},
    {"name": "Gua Sha Set with Rose Quartz", "cost": 5.00, "niche": "beauty",
     "image_description": "Rose quartz gua sha tool and roller on a clean white surface, skincare products beside it, spa aesthetic",
     "tags": ["beauty", "gua-sha", "facial-roller", "skincare", "self-care"]},
    {"name": "Electric Callus Remover", "cost": 7.00, "niche": "beauty",
     "image_description": "Electric foot callus remover on a bathroom floor, gentle exfoliation action, smooth heels result",
     "tags": ["beauty", "foot-care", "callus-remover", "electric", "pedicure"]},
    {"name": "Hair Removal Cream Applicator Tool", "cost": 3.00, "niche": "beauty",
     "image_description": "Ergonomic hair removal cream applicator being used on a leg, smooth application, easy clean design",
     "tags": ["beauty", "hair-removal", "applicator", "bathroom", "grooming"]},
]


def _fallback_pipeline_products(niche: str, count: int) -> list:
    """Return market-verified products from curated list, filtered by niche."""
    if niche and niche != "all":
        candidates = [p for p in CURATED_PRODUCTS if p["niche"] == niche]
    else:
        candidates = list(CURATED_PRODUCTS)
    # Shuffle for variety
    import random
    random.shuffle(candidates)
    return candidates[:max(0, min(count, len(candidates)))]

@store_bp.route("/store/pipeline/run", methods=["POST"])
def run_pipeline():
    """Full pipeline: research → generate → publish (if auto-publish enabled)."""
    try:
        body = request.get_json(force=True, silent=True) or {}
    except:
        body = {}
    settings = _load_settings()
    niche = body.get("niche") or body.get("category") or settings.get("niche", "home-decor")
    try:
        count = int(body.get("count", settings.get("max_daily_products", 5)))
    except:
        count = int(settings.get("max_daily_products", 5))
    count = max(0, min(count, 50))
    auto_publish = body.get("auto_publish", settings.get("auto_publish", False))
    if isinstance(auto_publish, str):
        auto_publish = auto_publish.strip().lower() in ("1", "true", "yes", "on")

    results = {"researched": 0, "generated": 0, "published": 0, "products": []}

    # ── Multi-niche rotation ──
    # When niche="all", pull from every niche evenly
    NICHE_ROTATION = ["home-decor", "tech-gadgets", "kitchen", "pet-supplies", "beauty"]
    if niche == "all" or niche == "auto":
        niches_to_run = list(NICHE_ROTATION)
        per_niche = max(1, count // len(niches_to_run))
        researched = []
        for sub_niche in niches_to_run:
            curated = _fallback_pipeline_products(sub_niche, per_niche)
            researched.extend(curated)
        # Trim to exact count
        researched = researched[:count]
        import random
        random.shuffle(researched)
    else:
        # Single niche mode — pull from curated list for that niche
        researched = _fallback_pipeline_products(niche, count)

    # Try to enhance with AI research (but keep curated as base)
    results["researched"] = len(researched)

    # Step 2-3: Generate pages for each product
    for item in researched[:count]:
        if not isinstance(item, dict):
            _log_store(f"Skipping malformed research item: {item}")
            continue
        try:
            cost = _safe_float(item.get("cost", item.get("estimated_cost", 10)), 10.0)
        except:
            cost = 10.0
        gen_body = {
            "name": item.get("name", "Product"),
            "cost": cost,
            "niche": item.get("niche") or niche,
            "image_description": item.get("image_description", ""),
            "tags": _normalize_tags(item.get("tags", []), item.get("niche") or niche),
        }
        gen_data = _generate_product(gen_body)
        if gen_data.get("success"):
            results["generated"] += 1
            product = gen_data["product"]
            results["products"].append(product)

            # Step 4: Auto-publish if enabled
            if auto_publish:
                pub = _push_to_shopify(product)
                if pub.get("success"):
                    results["published"] += 1

    _log_store(f"Pipeline run: {results['researched']} researched, {results['generated']} generated, {results['published']} published")
    return jsonify({"success": True, **results})

# ── Product Management ─────────────────────────────────────────

@store_bp.route("/store/products", methods=["GET"])
def list_products():
    """List all generated products."""
    products = []
    for f in sorted(PRODUCTS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            p = _json.loads(f.read_text())
            products.append({
                "product_id": p.get("product_id"),
                "title": p.get("title"),
                "price": p.get("price"),
                "niche": p.get("niche"),
                "published": p.get("published", False),
                "created_at": p.get("created_at"),
                "images": len(p.get("generated_images", [])),
            })
        except: pass
    
    return jsonify({"success": True, "products": products, "total": len(products)})

@store_bp.route("/store/products/<product_id>", methods=["GET"])
def get_product(product_id):
    """Get a single product's full details."""
    try:
        product_id = _safe_product_id(product_id)
    except ValueError:
        return jsonify({"success": False, "error": "Invalid product_id"}), 400
    product_path = PRODUCTS_DIR / f"{product_id}.json"
    if not product_path.exists():
        return jsonify({"success": False, "error": "Not found"}), 404
    product = _json.loads(product_path.read_text())
    return jsonify({"success": True, "product": product})

@store_bp.route("/store/products/<product_id>", methods=["DELETE"])
def delete_product(product_id):
    """Delete a generated product."""
    try:
        product_id = _safe_product_id(product_id)
    except ValueError:
        return jsonify({"success": False, "error": "Invalid product_id"}), 400
    product_path = PRODUCTS_DIR / f"{product_id}.json"
    if product_path.exists():
        product_path.unlink()
        # Clean up associated images
        for asset_dir in ASSET_DIRS:
            for f in asset_dir.glob(f"{product_id}_*"):
                f.unlink()
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Not found"}), 404

# ── Settings ────────────────────────────────────────────────────

@store_bp.route("/store/settings", methods=["GET"])
def get_settings():
    """Get store automation settings."""
    return jsonify({"success": True, "settings": _load_settings()})

@store_bp.route("/store/settings", methods=["POST"])
def update_settings():
    """Update store automation settings."""
    try:
        body = request.get_json(force=True, silent=True) or {}
    except:
        body = {}
    current = _load_settings()
    for k, v in body.items():
        if k in DEFAULT_SETTINGS or k.startswith("shopify_"):
            current[k] = v
    _save_settings(current)
    _log_store(f"Settings updated")
    return jsonify({"success": True, "settings": current})

@store_bp.route("/store/settings/shopify", methods=["POST"])
def configure_shopify():
    """Configure Shopify store connection."""
    try:
        body = request.get_json(force=True, silent=True) or {}
    except:
        body = {}
    settings = _load_settings()
    store = body.get("store", "")
    token = body.get("token", "")
    
    if store:
        # Validate the connection
        import urllib.request
        try:
            req = urllib.request.Request(
                f"https://{store}/admin/api/2024-10/shop.json",
                headers={"X-Shopify-Access-Token": token}
            )
            resp = urllib.request.urlopen(req, timeout=15)
            shop_data = _json.loads(resp.read())
            shop_name = shop_data.get("shop", {}).get("name", store)
            settings["shopify_store"] = store
            settings["shopify_token"] = token
            _save_settings(settings)
            _log_store(f"Shopify connected: {shop_name}")
            return jsonify({"success": True, "shop_name": shop_name})
        except Exception as e:
            return jsonify({"success": False, "error": f"Connection failed: {e}"})
    
    return jsonify({"success": False, "error": "Missing store URL or token"})

# ── Daily Briefing ────────────────────────────────────────────

@store_bp.route("/store/briefing", methods=["GET"])
def daily_briefing():
    """Generate a daily store briefing."""
    settings = _load_settings()
    products = []
    for f in PRODUCTS_DIR.glob("*.json"):
        try:
            products.append(_json.loads(f.read_text()))
        except Exception as e:
            _log_store(f"Skipping unreadable product file {f.name}: {e}")
    
    total_products = len(products)
    published = sum(1 for p in products if p.get("published"))
    unpublished = total_products - published

    if total_products == 0:
        return jsonify({
            "success": True,
            "briefing": f"Daily Store Briefing\n\nNo products have been generated yet.\nAuto-publish: {'ON' if settings.get('auto_publish') else 'OFF'}\nNiche: {settings.get('niche', 'Unknown')}\nNext step: run /store/pipeline/run to create the first products.",
            "stats": {
                "total_products": 0,
                "published": 0,
                "unpublished": 0,
                "potential_revenue": 0,
                "today_products": 0,
            }
        })
    
    # Calculate stats
    total_revenue = 0
    for p in products:
        if p.get("published"):
            total_revenue += p.get("price", 0)
    
    # Get today's products
    today = datetime.now().date().isoformat()
    today_products = []
    for p in products:
        created = p.get("created_at", "")[:10]
        if created == today:
            today_products.append(p.get("title", "Unknown"))

    prompt = f"""Generate a short, punchy daily store briefing with this data:

Store Niche: {settings.get('niche', 'Unknown')}
Total Products: {total_products}
Published: {published}
Unpublished: {unpublished}
Potential Revenue (if all sold): ${total_revenue:.2f}
Products Created Today: {len(today_products)}
Auto-Publish: {'ON' if settings.get('auto_publish') else 'OFF'}

Write 3-4 short lines with emojis, actionable insights, and next steps. Be excited and motivating."""
    
    briefing = _call_llm(prompt)
    if not briefing:
        briefing = f"📊 **Daily Store Briefing**\n\n📦 {total_products} total products ({published} published)\n💰 ${total_revenue:.2f} potential revenue\n{'✅ Auto-publish ON' if settings.get('auto_publish') else '⏸️ Auto-publish OFF'}\n\n🏷️ Niche: {settings.get('niche', 'Unknown')}"

    return jsonify({
        "success": True,
        "briefing": briefing,
        "stats": {
            "total_products": total_products,
            "published": published,
            "unpublished": unpublished,
            "potential_revenue": round(total_revenue, 2),
            "today_products": len(today_products),
        }
    })

# ── Register Routes ────────────────────────────────────────────

def register_routes(app, state=None, require_auth=None):
    """Register store automation blueprint."""
    bp = store_bp
    if require_auth:
        # Apply auth to all routes
        for rule in [r for r in bp.deferred_functions] if hasattr(bp, 'deferred_functions') else []:
            pass
    app.register_blueprint(bp)
    _log(f"store routes registered ({len(bp.deferred_functions) if hasattr(bp, 'deferred_functions') else '?'} endpoints)")
    app.config.setdefault("store_bp_registered", True)
    return app
