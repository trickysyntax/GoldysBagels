#!/usr/bin/env python3
"""Generate new bagel/shmear illustrations + regenerate citrus-honey + standardize all sizes.

New items:
  - bagel-with-shmear   (By the Bagel: Bagel with Shmear $4)
  - egg-cheese-bagel    (By the Bagel: Egg & Cheese Bagel $8)
  - nova-lox            (Loaded Nova Lox $12, below shmears + signature section)
  - shmear-citrus-honey (REGENERATED with magenta chroma key instead of green)

Post-processing: ALL thumbnails get trimmed, resized to consistent scale,
and padded to 256×256 so subjects fill the same relative area.
"""

import json, random, time, os, base64
import urllib.request, urllib.parse
from PIL import Image
import numpy as np

HOST = "http://comfy.ciderhouse.org"
AUTH = "openclaw:qaxqyk-wohvyf-2Fovzi"
OUTPUT_DIR = "/Users/josh/GoldysBagels/assets/thumbs"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Style based on real Goldy's Bagels photos:
# - Deep golden-brown to dark caramel crust
# - Glossy, lacquered, shiny surface (boiled-then-baked)
# - Blistered, bubbled texture
# - Plump, hand-formed, slightly irregular
# - Warm jewel-tone palette, hand-drawn outlines
STYLE_GREEN = (
    "whimsical food illustration, three-quarter view, warm jewel-tone palette, "
    "soft hand-drawn outlines in warm brown not black, playful and charming, "
    "top-left lighting with soft warm shadows, glossy appetizing textures, "
    "glossy lacquered golden-brown crust with blistered bubbled surface like authentic boiled bagels, "
    "plump hand-formed slightly irregular shape, "
    "clean vector-like rendering with subtle texture details, "
    "solid bright green #00FF00 chromakey background, centered, no text, no letters, no watermark"
)

STYLE_MAGENTA = (
    "whimsical food illustration, three-quarter view, warm jewel-tone palette, "
    "soft hand-drawn outlines in warm brown not black, playful and charming, "
    "top-left lighting with soft warm shadows, glossy appetizing textures, "
    "clean vector-like rendering with subtle texture details, "
    "solid bright magenta #FF00FF chromakey background, centered, no text, no letters, no watermark"
)

# Items to generate: name -> (description, chroma_key_color)
# chroma_key_color: 'green' or 'magenta'
ITEMS = {
    # New menu illustrations
    "bagel-with-shmear": (
        "a bagel sliced in half horizontally showing a thick generous layer of white cream cheese shmear "
        "between the two toasted golden-brown halves, creamy swirl visible, three-quarter view",
        "green"
    ),
    "egg-cheese-bagel": (
        "a breakfast sandwich on a golden-brown bagel, fried egg with gooey melted American cheese "
        "peeking out from between the halves, warm and delicious, three-quarter view",
        "green"
    ),
    "nova-lox": (
        "a loaded open-faced Nova lox bagel sandwich, everything bagel with cream cheese, "
        "silky smoked salmon draped on top, capers, thin red onion slices, fresh dill sprigs, "
        "garnished beautifully, three-quarter view",
        "green"
    ),
    # Regenerated with magenta chroma key (green was eating the yellow-green citrus colors)
    "shmear-citrus-honey": (
        "a small rustic bowl of citrus honey cream cheese shmear, creamy white with bright orange "
        "citrus zest swirls and golden honey drizzle on top, wooden spoon, appetizing",
        "magenta"
    ),
}

def submit_workflow(prompt_text, seed, filename_prefix, width=256, height=256):
    """Submit a Flux Schnell workflow to the ComfyUI server."""
    workflow = {
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "flux1-schnell-fp8.safetensors"}
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": prompt_text, "clip": ["4", 1]}
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["13", 0], "vae": ["4", 2]}
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {"images": ["8", 0], "filename_prefix": filename_prefix}
        },
        "13": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed, "steps": 4, "cfg": 1.0,
                "sampler_name": "euler", "scheduler": "normal",
                "denoise": 1.0, "model": ["4", 0],
                "positive": ["6", 0], "negative": ["6", 0],
                "latent_image": ["15", 0]
            }
        },
        "15": {
            "class_type": "EmptySD3LatentImage",
            "inputs": {"width": width, "height": height, "batch_size": 1}
        }
    }

    prompt_data = json.dumps({"prompt": workflow}).encode("utf-8")
    req = urllib.request.Request(
        f"{HOST}/api/prompt",
        data=prompt_data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    req.add_header("Authorization", "Basic " + base64.b64encode(AUTH.encode()).decode())
    resp = urllib.request.urlopen(req, timeout=30)
    result = json.loads(resp.read())
    return result.get("prompt_id")

def poll_history(prompt_id, timeout=300):
    """Poll /history until the job completes."""
    start = time.time()
    while time.time() - start < timeout:
        url = f"{HOST}/history?prompt_id={prompt_id}"
        req = urllib.request.Request(url)
        req.add_header("Authorization", "Basic " + base64.b64encode(AUTH.encode()).decode())
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read())
        if prompt_id in data:
            return data[prompt_id]
        time.sleep(3)
    return None

def download_image(filename, subfolder, output_path):
    """Download an output image from the server."""
    params = urllib.parse.urlencode({"filename": filename, "type": "output", "subfolder": subfolder or ""})
    url = f"{HOST}/api/view?{params}"
    req = urllib.request.Request(url)
    req.add_header("Authorization", "Basic " + base64.b64encode(AUTH.encode()).decode())
    resp = urllib.request.urlopen(req, timeout=30)
    with open(output_path, "wb") as f:
        f.write(resp.read())

def chroma_key(src_path, dst_path, key_color='green'):
    """Remove chroma key background and save transparent PNG at 256×256."""
    img = Image.open(src_path).convert("RGBA")
    d = np.array(img)
    r, g, b = d[:,:,0], d[:,:,1], d[:,:,2]

    if key_color == 'green':
        # Green chroma key: #00FF00
        mask = (g > 120) & (g > r * 1.2) & (g > b * 1.2)
    elif key_color == 'magenta':
        # Magenta chroma key: #FF00FF
        mask = (r > 120) & (b > 120) & (r > g * 1.8) & (b > g * 1.8)
    else:
        raise ValueError(f"Unknown key color: {key_color}")

    d[mask, 3] = 0  # Set alpha to 0 for masked pixels

    # Clamp the key color channel on remaining pixels to remove fringe
    if key_color == 'green':
        # Clamp green channel where it's disproportionately high
        fringe = (g > r * 1.05) & (g > b * 1.05) & (d[:,:,3] > 0)
        d[fringe, 1] = np.minimum(d[fringe, 0], d[fringe, 2])  # Set green to min(r,b)
    elif key_color == 'magenta':
        # Clamp red and blue where they're disproportionately high vs green
        fringe_r = (r > g * 1.5) & (d[:,:,3] > 0)
        fringe_b = (b > g * 1.5) & (d[:,:,3] > 0)
        d[fringe_r, 0] = d[fringe_r, 1]  # Set red to green level
        d[fringe_b, 2] = d[fringe_b, 1]  # Set blue to green level

    # Kill low-alpha fringe artifacts (partial transparency at edges)
    low_alpha = d[:,:,3] < 20
    d[low_alpha, 3] = 0

    img = Image.fromarray(d)
    img = img.resize((256, 256), Image.LANCZOS)
    img.save(dst_path)
    return img

def standardize_size(src_path, dst_path, target_subject_size=200, canvas_size=256):
    """Trim transparent borders, resize subject to consistent scale, center on canvas.
    
    This ensures all illustrations have their subject at the same relative size.
    """
    img = Image.open(src_path).convert("RGBA")
    d = np.array(img)
    alpha = d[:,:,3]

    # Find bounding box of non-transparent pixels
    rows = np.any(alpha > 0, axis=1)
    cols = np.any(alpha > 0, axis=0)
    if not rows.any() or not cols.any():
        # Fully transparent — save as-is
        img.save(dst_path)
        return

    rmin, rmax = np.where(rows)[0][[0, -1]]
    cmin, cmax = np.where(cols)[0][[0, -1]]

    # Crop to bounding box
    cropped = img.crop((cmin, rmin, cmax + 1, rmax + 1))

    # Resize so the longest dimension is target_subject_size
    w, h = cropped.size
    if w >= h:
        new_w = target_subject_size
        new_h = int(h * target_subject_size / w)
    else:
        new_h = target_subject_size
        new_w = int(w * target_subject_size / h)

    resized = cropped.resize((new_w, new_h), Image.LANCZOS)

    # Center on transparent canvas
    canvas = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    offset = ((canvas_size - new_w) // 2, (canvas_size - new_h) // 2)
    canvas.paste(resized, offset, resized)
    canvas.save(dst_path)
    return canvas

def main():
    # Phase 1: Generate new + regenerated illustrations
    total = len(ITEMS)
    completed = 0
    failed = []

    for name, (description, key_color) in ITEMS.items():
        print(f"\n[{completed+1}/{total}] Generating: {name}")
        print(f"  Description: {description[:80]}...")
        print(f"  Chroma key: {key_color}")

        style = STYLE_MAGENTA if key_color == 'magenta' else STYLE_GREEN
        full_prompt = f"{description}, {style}"
        seed = random.randint(1, 2**32)
        prefix = f"goldy_{name}"

        try:
            prompt_id = submit_workflow(full_prompt, seed, prefix)
            if not prompt_id:
                print(f"  ERROR: No prompt_id returned")
                failed.append(name)
                completed += 1
                continue

            print(f"  Submitted: {prompt_id}")
            print(f"  Waiting for completion...")
            result = poll_history(prompt_id, timeout=300)
            if not result:
                print(f"  ERROR: Timeout waiting for completion")
                failed.append(name)
                completed += 1
                continue

            outputs = result.get("outputs", {})
            for node_id, node_output in outputs.items():
                if "images" in node_output:
                    for img_info in node_output["images"]:
                        filename = img_info["filename"]
                        subfolder = img_info.get("subfolder", "")

                        raw_path = os.path.join(OUTPUT_DIR, f"{name}_raw.png")
                        download_image(filename, subfolder, raw_path)
                        print(f"  Downloaded: {filename} ({os.path.getsize(raw_path)} bytes)")

                        # Chroma key
                        keyed_path = os.path.join(OUTPUT_DIR, f"{name}_keyed.png")
                        chroma_key(raw_path, keyed_path, key_color=key_color)
                        print(f"  Chroma keyed: {keyed_path}")

                        os.remove(raw_path)
                        break

            completed += 1

        except Exception as e:
            print(f"  ERROR: {e}")
            failed.append(name)
            completed += 1

    print(f"\n{'='*50}")
    print(f"Generation: {completed - len(failed)}/{total} succeeded")
    if failed:
        print(f"Failed: {', '.join(failed)}")

    # Phase 2: Standardize ALL thumbnails in the directory
    print(f"\n{'='*50}")
    print("Phase 2: Standardizing all thumbnail sizes...")

    all_pngs = sorted([f for f in os.listdir(OUTPUT_DIR) if f.endswith('.png') and '_raw' not in f and '_keyed' not in f])
    print(f"Found {len(all_pngs)} thumbnails to standardize")

    for fname in all_pngs:
        src = os.path.join(OUTPUT_DIR, fname)

        # For newly generated items, use the _keyed version as source
        keyed = os.path.join(OUTPUT_DIR, fname.replace('.png', '_keyed.png'))
        if os.path.exists(keyed):
            src = keyed

        dst = os.path.join(OUTPUT_DIR, fname)
        try:
            standardize_size(src, dst)
            print(f"  ✓ {fname}")
        except Exception as e:
            print(f"  ✗ {fname}: {e}")

    # Clean up _keyed temp files
    for f in os.listdir(OUTPUT_DIR):
        if '_keyed' in f:
            os.remove(os.path.join(OUTPUT_DIR, f))
            print(f"  Cleaned up: {f}")

    print(f"\nDone! All thumbnails standardized to 256×256 with consistent subject sizing.")

if __name__ == "__main__":
    main()
