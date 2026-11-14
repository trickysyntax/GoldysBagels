#!/usr/bin/env python3
"""Generate bagel + shmear illustrations via ComfyUI Flux Schnell with green chroma key."""

import json, random, time, sys, os, base64
import urllib.request, urllib.parse
from PIL import Image
import numpy as np

HOST = "http://comfy.ciderhouse.org"
AUTH = "openclaw:qaxqyk-wohvyf-2Fovzi"
OUTPUT_DIR = "/Users/josh/GoldysBagels/assets/thumbs"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Whimsical illustration style inspired by myPad/spire sprite work
# but adapted for food illustrations — warm, jewel-tone, isometric-ish
STYLE = (
    "whimsical food illustration, three-quarter view, warm jewel-tone palette, "
    "soft hand-drawn outlines in warm brown not black, playful and charming, "
    "top-left lighting with soft warm shadows, glossy appetizing textures, "
    "clean vector-like rendering with subtle texture details, "
    "solid bright green #00FF00 chromakey background, centered, no text, no letters, no watermark"
)

ITEMS = {
    # Bagels
    "bagel-plain": "a single plain bagel, golden brown crust, smooth shiny top, no seeds, perfectly round with a centered hole",
    "bagel-sesame": "a single sesame bagel, golden crust generously topped with toasted sesame seeds, centered hole",
    "bagel-everything": "a single everything bagel, golden crust coated with poppy seeds sesame seeds dried onion flakes garlic bits and salt, centered hole",
    "bagel-cinnamon-raisin": "a single cinnamon raisin bagel, warm brown dough studded with plump raisins and swirled with cinnamon, centered hole",
    "bagel-egg": "a single egg bagel, rich yellow-gold crust, slightly glossy, eggy golden color, centered hole",
    "bagel-dark-chocolate": "a single dark chocolate bagel, deep cocoa brown dough with dark chocolate chunks and streaks, centered hole",
    # Shmears
    "shmear-plain": "a small rustic bowl of plain cream cheese shmear, smooth white creamy spread, dollop with a swirl, wooden spoon",
    "shmear-lox": "a small rustic bowl of lox spread cream cheese, pink-orange salmon flecks mixed into creamy white spread, capers and dill garnish",
    "shmear-citrus-honey": "a small rustic bowl of citrus honey cream cheese, creamy white with bright orange citrus zest swirls and golden honey drizzle",
    "shmear-jalapeno-cheddar": "a small rustic bowl of jalapeno cheddar cream cheese, creamy base with green jalapeno bits and orange cheddar flecks throughout",
}

def submit_workflow(prompt_text, seed, filename_prefix):
    """Submit a Flux Schnell workflow to the ComfyUI server."""
    workflow = {
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {
                "ckpt_name": "flux1-schnell-fp8.safetensors"
            }
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "text": prompt_text,
                "clip": ["4", 1]
            }
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {
                "samples": ["13", 0],
                "vae": ["4", 2]
            }
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {
                "images": ["8", 0],
                "filename_prefix": filename_prefix
            }
        },
        "13": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": 4,
                "cfg": 1.0,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 1.0,
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["6", 0],
                "latent_image": ["15", 0]
            }
        },
        "15": {
            "class_type": "EmptySD3LatentImage",
            "inputs": {
                "width": 256,
                "height": 256,
                "batch_size": 1
            }
        },
        "8": {

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

def chroma_key_green(src_path, dst_path, target_size=128):
    """Remove green chroma key background and save transparent PNG."""
    img = Image.open(src_path).convert("RGBA")
    d = np.array(img)
    r, g, b = d[:,:,0], d[:,:,1], d[:,:,2]

    # Green chroma key
    mask = (g > 120) & (g > r * 1.2) & (g > b * 1.2)
    d[mask, 3] = 0

    # Also remove near-white pixels that might be background bleed
    # (only if they're very bright and not part of the subject)
    white_mask = (r > 240) & (g > 240) & (b > 240)
    # Only remove white pixels that are adjacent to transparent pixels
    # (this is conservative — we don't want to eat cream cheese!)
    # Skip this for now; the green key should be sufficient

    img = Image.fromarray(d)
    img = img.resize((target_size, target_size), Image.LANCZOS)
    img.save(dst_path)
    return img

def main():
    total = len(ITEMS)
    completed = 0
    failed = []

    for name, description in ITEMS.items():
        print(f"\n[{completed+1}/{total}] Generating: {name}")
        print(f"  Description: {description[:80]}...")

        full_prompt = f"{description}, {STYLE}"
        seed = random.randint(1, 2**32)
        prefix = f"goldy_{name}"

        try:
            # Submit
            prompt_id = submit_workflow(full_prompt, seed, prefix)
            if not prompt_id:
                print(f"  ERROR: No prompt_id returned")
                failed.append(name)
                completed += 1
                continue

            print(f"  Submitted: {prompt_id}")

            # Poll for completion
            print(f"  Waiting for completion...")
            result = poll_history(prompt_id, timeout=300)
            if not result:
                print(f"  ERROR: Timeout waiting for completion")
                failed.append(name)
                completed += 1
                continue

            # Extract output filename
            outputs = result.get("outputs", {})
            for node_id, node_output in outputs.items():
                if "images" in node_output:
                    for img_info in node_output["images"]:
                        filename = img_info["filename"]
                        subfolder = img_info.get("subfolder", "")

                        # Download raw image
                        raw_path = os.path.join(OUTPUT_DIR, f"{name}_raw.png")
                        download_image(filename, subfolder, raw_path)
                        print(f"  Downloaded: {filename} ({os.path.getsize(raw_path)} bytes)")

                        # Chroma key + resize
                        final_path = os.path.join(OUTPUT_DIR, f"{name}.png")
                        chroma_key_green(raw_path, final_path, target_size=256)
                        print(f"  Chroma keyed: {final_path}")

                        # Clean up raw
                        os.remove(raw_path)
                        break

            completed += 1

        except Exception as e:
            print(f"  ERROR: {e}")
            failed.append(name)
            completed += 1

    print(f"\n{'='*50}")
    print(f"Done! {completed - len(failed)}/{total} succeeded")
    if failed:
        print(f"Failed: {', '.join(failed)}")
    print(f"Output: {OUTPUT_DIR}")

if __name__ == "__main__":
    main()
