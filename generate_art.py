#!/usr/bin/env python3
"""
Generate bagel/shmear thumbnail art via ComfyUI Flux Schnell.

Important: this workflow intentionally avoids IPAdapter/style-reference nodes. The old
IPAdapter + carrot_ref workflow overpowered the text prompt, making every bagel converge
toward the same golden seeded shape. This script relies on explicit per-variety prompts
and chroma-key post processing so color/flavor differences actually survive.
"""
import json, random, time, os, base64, sys
import urllib.request, urllib.parse
from PIL import Image, ImageOps, ImageEnhance, ImageFilter
import numpy as np

HOST = os.environ.get("COMFY_HOST", "http://comfy.ciderhouse.org")
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "/var/www/goldysbagels/assets/thumbs")
AUTH = os.environ.get("COMFY_AUTH", "openclaw:qaxqyk-wohvyf-2Fovzi")


def _auth():
    return "Basic " + base64.b64encode(AUTH.encode()).decode()


# ─── Subject descriptions ──────────────────────────────────────────────

BAGEL_DESC = {
    "plain": (
        "one single plain bagel, warm golden tan bread crust with irregular baked patches, "
        "pale cream highlights and darker caramel toasted areas, broad patch shapes not tiny dots, "
        "absolutely no sesame seeds, no poppy seeds, no toppings, no seed speckles, classic ring shape with an open transparent center hole"
    ),
    "salt": (
        "one single salt bagel, pale golden tan bread crust with broad irregular baked patches, "
        "scattered chunky coarse white salt crystals sitting on top of the crust, the salt grains are "
        "large, angular and clearly visible against the bread, no sesame seeds, no poppy seeds, "
        "no onion, no garlic, no other seasoning, classic ring shape with an open transparent center hole"
    ),
    "sesame": (
        "one single sesame bagel, light tan bread crust covered with many pale oval sesame seeds, "
        "seeds are raised on top of the crust, no poppy seeds, no chocolate, centered hole"
    ),
    "everything": (
        "one single everything bagel, tan crust heavily coated with mixed black poppy seeds, "
        "pale sesame seeds, dried onion flakes, garlic bits, and coarse salt crystals, "
        "busy speckled seasoning texture across the whole top, centered hole"
    ),
    "cinnamon raisin": (
        "one single cinnamon raisin bagel, warm golden cinnamon-brown dough with irregular baked patches, "
        "darker cinnamon ribbons and folds baked into the dough, many dark glossy raisins embedded in the surface, "
        "raisins have tiny brown highlights, no seeds, no sesame, open transparent center hole"
    ),
    "egg": (
        "one single egg bagel, rich yellow egg dough, saturated yellow-gold smooth glossy crust, "
        "plain surface with no seeds and no toppings, centered hole"
    ),
    "dark chocolate": (
        "one single dark chocolate bagel, the entire bagel dough is very dark cocoa brown, "
        "almost espresso colored with darker toasted shadow patches and muted reddish-brown highlights, "
        "dark brown chocolate chunks and chips embedded in the surface, chunks have tiny glossy brown highlights, "
        "no white chunks, no sesame seeds, no golden crust, open transparent center hole"
    ),
}

SHMEAR_DESC = {
    "plain cream cheese": "a small simple bowl filled with smooth plain cream cheese, bright white creamy spread, soft dollop with a swirl, no herbs or mix-ins",
    "lox spread": "a small simple bowl of lox spread cream cheese, white cream cheese mixed with orange-pink smoked salmon flecks, small green capers and dill garnish",
    "arizona citrus & honey": "a small simple bowl of citrus honey cream cheese, white cream cheese with orange citrus zest swirls and glossy honey drizzle",
    "jalapeno cheddar": "a small simple bowl of jalapeno cheddar cream cheese, white cream cheese with green jalapeno bits and orange cheddar flecks throughout",
}


def get_desc(item_type, name):
    nl = name.lower().strip()
    if item_type == "bagel":
        d = BAGEL_DESC.get(nl)
        if d:
            return d
        # Better unknown fallbacks: honor color/flavor words instead of forcing golden.
        if "chocolate" in nl or "cocoa" in nl:
            return f"one single {nl} bagel, very dark cocoa brown dough, dark chocolate chunks, no white chunks, no sesame seeds, centered hole"
        if "cinnamon" in nl or "raisin" in nl:
            return f"one single {nl} bagel, medium cinnamon brown dough, dark raisins, cinnamon ribbons, no seeds, centered hole"
        if "sesame" in nl:
            return f"one single {nl} bagel, tan crust covered with pale sesame seeds, centered hole"
        if "everything" in nl:
            return f"one single {nl} bagel, tan crust covered with mixed black and white everything seasoning speckles, centered hole"
        return f"one single {nl} bagel, plain tan bread crust, flavor-specific color and toppings, centered hole"
    d = SHMEAR_DESC.get(nl)
    return d or f"a small simple bowl of {nl} cream cheese spread, flavor-specific mix-ins visible, creamy texture"


def slugify(name, item_type="bagel"):
    s = name.lower().replace("'", "").replace("&", "and")
    s = "-".join(s.split())
    s = "".join(c for c in s if c.isalnum() or c == "-")
    return f"{item_type}-{s.strip('-')}"


# ─── Prompting ──────────────────────────────────────────────────────────

STYLE_BASE = (
    "charming flat vector sticker-style food illustration, thick dark outline, "
    "rounded geometric shapes, minimal cel shading, soft floating shadow, "
    "clean Adobe Illustrator vector art, simple wholesome playful design, "
    "centered single object, plain solid bright green #00FF00 chromakey background, "
    "not cropped, not cut off, not touching the frame edge, "
    "direct overhead view, crisp edges, no plate, no table, no props, no text, no watermark, "
    "use the exact food colors from the subject description"
)

STYLE_BAGEL = STYLE_BASE + (
    ", same thick dark contour around the inside edge of the bagel hole, "
    "layered crust texture with broad irregular tan, caramel, and dark brown patches, "
    "open transparent center hole with a bold inner stroke, "
    "do not normalize all bagels to golden"
)

STYLE_SHMEAR = STYLE_BASE + (
    ", overhead view of a small round bowl or ramekin filled with creamy spread, "
    "smooth or textured cream cheese surface with visible mix-ins matching the flavor, "
    "soft rounded container rim, no hole, no ring shape, no bread, no bagel"
)

def get_style(item_type):
    return STYLE_SHMEAR if item_type == "shmear" else STYLE_BAGEL

NEGATIVE_BASE = (
    "same generic bagel, identical bagels, default golden bagel, sesame seeds unless requested, tiny random dots, "
    "white chocolate chunks, white chips, white chunks, white squiggles, random seeds, cropped, cut off, truncated, touching image edge, "
    "photorealistic, 3d render, cgi, watercolor, rough sketch, line art only, simple emoji, flat plain emoji icon, "
    "background scene, plate, table, multiple objects, text, letters, logo, watermark"
)

NEGATIVE_SHMEAR = (
    "bagel, bread, donut, ring shape, hole, center hole, crust, sesame seeds, poppy seeds, "
    "cropped, cut off, truncated, touching image edge, "
    "photorealistic, 3d render, cgi, watercolor, rough sketch, line art only, simple emoji, flat plain emoji icon, "
    "background scene, plate, table, multiple objects, text, letters, logo, watermark"
)

ITEM_NEGATIVE = {
    "plain": "sesame seeds, poppy seeds, everything seasoning, chocolate chips, raisins, cinnamon swirls, speckles",
    "salt": "sesame seeds, poppy seeds, everything seasoning, dried onion flakes, garlic bits, chocolate chips, raisins, cinnamon swirls, black speckles",
    "sesame": "poppy seeds, everything seasoning, chocolate chips, raisins, cinnamon swirls, plain smooth top with no seeds",
    "everything": "plain smooth top, only sesame seeds, chocolate chips, raisins, cinnamon swirls",
    "cinnamon raisin": "sesame seeds, poppy seeds, white squiggles, white icing, chocolate chips, golden plain dough",
    "egg": "sesame seeds, poppy seeds, chocolate chips, raisins, dark brown chocolate dough",
    "dark chocolate": "golden crust, tan crust, yellow bagel, sesame seeds, poppy seeds, white chocolate, white chunks, white chips, icing, cinnamon squiggles",
}


def negative_for(item_type, name):
    if item_type == "shmear":
        return NEGATIVE_SHMEAR
    return NEGATIVE_BASE + ", " + ITEM_NEGATIVE.get(name.lower().strip(), "")


# ─── ComfyUI API helpers ────────────────────────────────────────────────

def submit(prompt_text, negative_text, seed, prefix, item_type="bagel", style_override=None):
    """Submit a Flux Schnell workflow. No IPAdapter/style reference on purpose."""
    positive = prompt_text + ", " + (style_override or get_style(item_type))
    wf = {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "flux1-schnell-fp8.safetensors"}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": positive, "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": negative_text, "clip": ["4", 1]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["13", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": prefix, "images": ["8", 0]}},
        "13": {"class_type": "KSampler", "inputs": {
            "seed": seed,
            "steps": 4,
            "cfg": 1.0,
            "sampler_name": "euler",
            "scheduler": "normal",
            "denoise": 1.0,
            "model": ["4", 0],
            "positive": ["6", 0],
            "negative": ["7", 0],
            "latent_image": ["15", 0],
        }},
        "15": {"class_type": "EmptySD3LatentImage", "inputs": {"width": 384, "height": 384, "batch_size": 1}},
    }
    data = json.dumps({"prompt": wf}).encode()
    req = urllib.request.Request(f"{HOST}/api/prompt", data=data,
        headers={"Content-Type": "application/json"}, method="POST")
    req.add_header("Authorization", _auth())
    r = urllib.request.urlopen(req, timeout=60)
    return json.loads(r.read()).get("prompt_id")


def poll(pid, timeout=600):
    start = time.time()
    while time.time() - start < timeout:
        req = urllib.request.Request(f"{HOST}/history/{pid}")
        req.add_header("Authorization", _auth())
        r = urllib.request.urlopen(req, timeout=15)
        d = json.loads(r.read())
        if pid in d:
            return d[pid]
        time.sleep(3)
    return None


def download(fn, sub, out):
    p = urllib.parse.urlencode({"filename": fn, "type": "output", "subfolder": sub or ""})
    req = urllib.request.Request(f"{HOST}/api/view?{p}")
    req.add_header("Authorization", _auth())
    r = urllib.request.urlopen(req, timeout=30)
    with open(out, "wb") as f:
        f.write(r.read())


# ─── Post-processing ───────────────────────────────────────────────────

def remove_bg(src, dst, canvas=256, subject_target=214):
    """Remove green chromakey background and standardize subject on transparent canvas."""
    img = Image.open(src).convert("RGBA")
    d = np.array(img)
    r, g, b = d[:, :, 0], d[:, :, 1], d[:, :, 2]

    # Remove bright green background. Keep food colors, including dark cocoa brown.
    green = (g > 120) & (g > r * 1.18) & (g > b * 1.18)
    d[green, 3] = 0

    # Desaturate green fringe near the subject without touching alpha/subject colors.
    fringe = (g > 80) & (g > r * 1.05) & (g > b * 1.05) & (d[:, :, 3] > 0)
    d[fringe, 1] = np.minimum(d[fringe, 1], ((d[fringe, 0].astype(int) + d[fringe, 2].astype(int)) // 2).astype(np.uint8))
    d[d[:, :, 3] < 25, 3] = 0

    img = Image.fromarray(d)

    # Reinforce the brand's cel-shaded icon look. Flux tends to soften gradients;
    # light contrast + posterization turns those into clearer highlight/shadow bands
    # without changing the prompt-driven food color (dark chocolate stays dark).
    alpha_img = img.getchannel("A")
    rgb = img.convert("RGB")
    rgb = ImageEnhance.Contrast(rgb).enhance(1.10)
    rgb = ImageOps.posterize(rgb, 6)
    img = Image.merge("RGBA", (*rgb.split(), alpha_img))

    # Trim transparent borders
    arr = np.array(img)
    alpha = arr[:, :, 3]
    rows = np.any(alpha > 0, axis=1)
    cols = np.any(alpha > 0, axis=0)
    if rows.any() and cols.any():
        rmin, rmax = np.where(rows)[0][[0, -1]]
        cmin, cmax = np.where(cols)[0][[0, -1]]
        img = img.crop((cmin, rmin, cmax + 1, rmax + 1))

    w, h = img.size
    if w >= h:
        nw, nh = subject_target, max(1, int(h * subject_target / w))
    else:
        nh, nw = subject_target, max(1, int(w * subject_target / h))
    resized = img.resize((nw, nh), Image.LANCZOS)

    cv = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    cv.paste(resized, ((canvas - nw) // 2, (canvas - nh) // 2), resized)

    cv = finish_target_style(cv)

    cv.save(dst)


def finish_target_style(img):
    """Add target-style contours while keeping the bagel hole transparent.

    The model is good at flavor differences; this deterministic finish makes the
    asset match the provided examples: big sticker silhouette, thick dark border,
    and the same stroke around the transparent inner cutout as the outside edge.
    """
    # First center/scale the generated subject with enough breathing room for a
    # heavy contour. Previous versions scaled the subject to ~242px and then
    # dilated the alpha mask, which clipped the right/bottom edge whenever the
    # generated bagel was slightly off-center.
    img = keep_largest_component(fit_to_canvas(img.convert("RGBA"), margin=18))
    arr = np.array(img)
    alpha = arr[:, :, 3] > 20

    # Find transparent regions connected to the canvas edge; enclosed transparent
    # regions are central holes. Keep those holes alpha, but use them to add a
    # thick inner stroke on the dough side.
    h, w = alpha.shape
    transparent = ~alpha
    outside = np.zeros_like(transparent, dtype=bool)
    stack = []
    for x in range(w):
        if transparent[0, x]: stack.append((0, x))
        if transparent[h - 1, x]: stack.append((h - 1, x))
    for y in range(h):
        if transparent[y, 0]: stack.append((y, 0))
        if transparent[y, w - 1]: stack.append((y, w - 1))

    while stack:
        y, x = stack.pop()
        if y < 0 or y >= h or x < 0 or x >= w or outside[y, x] or not transparent[y, x]:
            continue
        outside[y, x] = True
        stack.extend(((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)))

    holes = transparent & ~outside
    # Filter out tiny enclosed regions (gaps between fins, artifacts, etc.)
    # Only treat large enclosed areas as intentional holes (like a bagel center).
    if holes.any():
        hmask = holes.copy()
        labeled = np.zeros_like(hmask, dtype=np.int32)
        label = 0
        for yy in range(h):
            for xx in range(w):
                if not hmask[yy, xx] or labeled[yy, xx]:
                    continue
                label += 1
                stack2 = [(yy, xx)]
                hmask[yy, xx] = False
                labeled[yy, xx] = label
                count = 0
                while stack2:
                    cy, cx = stack2.pop()
                    count += 1
                    for ny, nx in ((cy-1,cx),(cy+1,cx),(cy,cx-1),(cy,cx+1)):
                        if 0 <= ny < h and 0 <= nx < w and hmask[ny, nx] and not labeled[ny, nx]:
                            hmask[ny, nx] = False
                            labeled[ny, nx] = label
                            stack2.append((ny, nx))
                if count < 200:
                    holes[labeled == label] = False
    if holes.any():
        # The hole itself stays transparent. The important part is the inner
        # contour: thicken the hole mask outward onto the dough so the inside
        # edge gets the same post-process stroke treatment as the outside edge.
        hole_alpha = Image.fromarray((holes * 255).astype(np.uint8), "L")
        inner_dilated = np.array(hole_alpha.filter(ImageFilter.MaxFilter(23))) > 0
        inner_contour = inner_dilated & alpha

        arr[inner_contour, 0] = 28
        arr[inner_contour, 1] = 20
        arr[inner_contour, 2] = 16
        arr[inner_contour, 3] = 255
        arr[holes, 3] = 0
        img = Image.fromarray(arr, "RGBA")

    # Thick dark outside contour. MaxFilter dilates alpha; difference becomes outline.
    # 23px kernel = ~11px contour, much closer to the reference examples and
    # consistent regardless of what the model rendered.
    alpha_img = img.getchannel("A")
    dilated = alpha_img.filter(ImageFilter.MaxFilter(23))
    outline_alpha = Image.fromarray(np.maximum(np.array(dilated) - np.array(alpha_img), 0).astype(np.uint8), "L")
    outline = Image.new("RGBA", img.size, (32, 24, 20, 0))
    outline.putalpha(outline_alpha)
    base = Image.new("RGBA", img.size, (0, 0, 0, 0))
    base.alpha_composite(outline)
    base.alpha_composite(img)
    return fit_to_canvas(base, margin=2)


def fit_to_canvas(img, margin=0):
    """Recenter and, if needed, scale non-transparent pixels inside canvas.

    Keeps the final PNG from clipping on any side even when the model produces an
    off-center subject or when the post-process contour is thick.
    """
    img = img.convert("RGBA")
    canvas_w, canvas_h = img.size
    arr = np.array(img)
    alpha = arr[:, :, 3] > 0
    if not alpha.any():
        return img

    ys, xs = np.where(alpha)
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    cropped = img.crop((x0, y0, x1 + 1, y1 + 1))
    max_w = max(1, canvas_w - margin * 2)
    max_h = max(1, canvas_h - margin * 2)
    scale = min(max_w / cropped.width, max_h / cropped.height, 1.0)
    if scale < 1.0:
        cropped = cropped.resize((max(1, int(cropped.width * scale)), max(1, int(cropped.height * scale))), Image.LANCZOS)

    out = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    out.alpha_composite(cropped, ((canvas_w - cropped.width) // 2, (canvas_h - cropped.height) // 2))
    return out


def keep_largest_component(img):
    """Drop stray alpha artifacts outside the generated subject."""
    img = img.convert("RGBA")
    arr = np.array(img)
    mask = arr[:, :, 3] > 20
    h, w = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    best = []

    for y in range(h):
        for x in range(w):
            if not mask[y, x] or seen[y, x]:
                continue
            comp = []
            stack = [(y, x)]
            seen[y, x] = True
            while stack:
                cy, cx = stack.pop()
                comp.append((cy, cx))
                for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                    if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
            if len(comp) > len(best):
                best = comp

    if not best:
        return img
    keep = np.zeros_like(mask, dtype=bool)
    ys, xs = zip(*best)
    keep[list(ys), list(xs)] = True
    arr[~keep, 3] = 0
    return Image.fromarray(arr, "RGBA")


# ─── Public function called by admin API ────────────────────────────────

def generate_art(item_type, name, guidance=""):
    """Generate thumbnail art. Always regenerates (replaces existing)."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    fn = slugify(name, item_type) + ".png"
    out = os.path.join(OUTPUT_DIR, fn)

    desc = guidance if guidance else get_desc(item_type, name)
    neg = negative_for(item_type, name)
    seed = random.randint(1, 2**32)
    prefix = "goldy_" + fn.replace(".png", "")

    pid = submit(desc, neg, seed, prefix, item_type, style_override=STYLE_BASE if guidance else None)
    if not pid:
        return False, "Failed to submit to ComfyUI"
    res = poll(pid, 600)
    if not res:
        return False, "ComfyUI generation timed out"
    for _nid, nout in res.get("outputs", {}).items():
        if "images" in nout:
            for img in nout["images"]:
                raw = out + ".raw.png"
                download(img["filename"], img.get("subfolder", ""), raw)
                remove_bg(raw, out, canvas=256)
                os.remove(raw)
                os.chmod(out, 0o644)
                return True, "Generated: " + fn
    return False, "No output images found"


def list_existing():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    b, s = [], []
    for f in sorted(os.listdir(OUTPUT_DIR)):
        if not f.endswith(".png") or f.startswith("."):
            continue
        if f.startswith("bagel-"):
            b.append(f)
        elif f.startswith("shmear-"):
            s.append(f)
    return {"bagels": b, "shmears": s}


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(json.dumps(list_existing(), indent=2))
        sys.exit(0)
    guidance = sys.argv[3] if len(sys.argv) > 3 else ""
    ok, msg = generate_art(sys.argv[1], sys.argv[2], guidance)
    print(msg)
    sys.exit(0 if ok else 1)
