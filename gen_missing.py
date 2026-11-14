#!/usr/bin/env python3
"""Generate the 3 missing menu illustrations, chroma key, and standardize."""
import json, random, time, os, base64
import urllib.request, urllib.parse
from PIL import Image
import numpy as np

HOST = "http://comfy.ciderhouse.org"
with open(os.path.join(os.path.dirname(__file__), ".env")) as _f:
    AUTH = _f.read().strip()
OUTPUT_DIR = "/Users/josh/GoldysBagels/assets/thumbs"

STYLE_GREEN = (
    "whimsical food illustration, three-quarter view, warm jewel-tone palette, "
    "soft hand-drawn outlines in warm brown not black, playful and charming, "
    "top-left lighting with soft warm shadows, glossy appetizing textures, "
    "glossy lacquered golden-brown crust with blistered bubbled surface like authentic boiled bagels, "
    "plump hand-formed slightly irregular shape, "
    "clean vector-like rendering with subtle texture details, "
    "solid bright green #00FF00 chromakey background, centered, no text, no letters, no watermark"
)

ITEMS = {
    "bagel-with-shmear": "a bagel sliced in half horizontally showing a thick generous layer of white cream cheese shmear between the two toasted golden-brown halves, creamy swirl visible, three-quarter view",
    "egg-cheese-bagel": "a breakfast sandwich on a golden-brown bagel, fried egg with gooey melted American cheese peeking out from between the halves, warm and delicious, three-quarter view",
    "nova-lox": "a loaded open-faced Nova lox bagel sandwich, everything bagel with cream cheese, silky smoked salmon draped on top, capers, thin red onion slices, fresh dill sprigs, garnished beautifully, three-quarter view",
}

def submit_workflow(prompt_text, seed, filename_prefix):
    workflow = {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "flux1-schnell-fp8.safetensors"}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt_text, "clip": ["4", 1]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["13", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": filename_prefix}},
        "13": {"class_type": "KSampler", "inputs": {
            "seed": seed, "steps": 4, "cfg": 1.0,
            "sampler_name": "euler", "scheduler": "normal",
            "denoise": 1.0, "model": ["4", 0],
            "positive": ["6", 0], "negative": ["6", 0],
            "latent_image": ["15", 0]
        }},
        "15": {"class_type": "EmptySD3LatentImage", "inputs": {"width": 256, "height": 256, "batch_size": 1}}
    }
    prompt_data = json.dumps({"prompt": workflow}).encode("utf-8")
    req = urllib.request.Request(f"{HOST}/api/prompt", data=prompt_data,
        headers={"Content-Type": "application/json"}, method="POST")
    req.add_header("Authorization", "Basic " + base64.b64encode(AUTH.encode()).decode())
    resp = urllib.request.urlopen(req, timeout=30)
    return json.loads(resp.read()).get("prompt_id")

def poll_history(prompt_id, timeout=300):
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
    params = urllib.parse.urlencode({"filename": filename, "type": "output", "subfolder": subfolder or ""})
    url = f"{HOST}/api/view?{params}"
    req = urllib.request.Request(url)
    req.add_header("Authorization", "Basic " + base64.b64encode(AUTH.encode()).decode())
    resp = urllib.request.urlopen(req, timeout=30)
    with open(output_path, "wb") as f:
        f.write(resp.read())

def chroma_key_green(src_path, dst_path):
    img = Image.open(src_path).convert("RGBA")
    d = np.array(img)
    r, g, b = d[:,:,0], d[:,:,1], d[:,:,2]
    mask = (g > 120) & (g > r * 1.2) & (g > b * 1.2)
    d[mask, 3] = 0
    fringe = (g > r * 1.05) & (g > b * 1.05) & (d[:,:,3] > 0)
    d[fringe, 1] = np.minimum(d[fringe, 0], d[fringe, 2])
    low_alpha = d[:,:,3] < 20
    d[low_alpha, 3] = 0
    img = Image.fromarray(d)
    img = img.resize((256, 256), Image.LANCZOS)
    img.save(dst_path)

def standardize_size(src_path, dst_path, target=200, canvas=256):
    img = Image.open(src_path).convert("RGBA")
    d = np.array(img)
    alpha = d[:,:,3]
    rows = np.any(alpha > 0, axis=1)
    cols = np.any(alpha > 0, axis=0)
    if not rows.any() or not cols.any():
        img.save(dst_path)
        return
    rmin, rmax = np.where(rows)[0][[0, -1]]
    cmin, cmax = np.where(cols)[0][[0, -1]]
    cropped = img.crop((cmin, rmin, cmax + 1, rmax + 1))
    w, h = cropped.size
    if w >= h:
        nw, nh = target, int(h * target / w)
    else:
        nh, nw = target, int(w * target / h)
    resized = cropped.resize((nw, nh), Image.LANCZOS)
    c = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    c.paste(resized, ((canvas - nw) // 2, (canvas - nh) // 2), resized)
    c.save(dst_path)

for name, description in ITEMS.items():
    print(f"\nGenerating: {name}")
    full_prompt = f"{description}, {STYLE_GREEN}"
    seed = random.randint(1, 2**32)
    prefix = f"goldy_{name}"

    prompt_id = submit_workflow(full_prompt, seed, prefix)
    print(f"  Submitted: {prompt_id}")
    result = poll_history(prompt_id, timeout=300)
    if not result:
        print(f"  ERROR: Timeout")
        continue

    for node_id, node_output in result.get("outputs", {}).items():
        if "images" in node_output:
            for img_info in node_output["images"]:
                filename = img_info["filename"]
                subfolder = img_info.get("subfolder", "")
                raw_path = os.path.join(OUTPUT_DIR, f"{name}_raw.png")
                download_image(filename, subfolder, raw_path)
                print(f"  Downloaded: {filename} ({os.path.getsize(raw_path)} bytes)")

                keyed_path = os.path.join(OUTPUT_DIR, f"{name}_keyed.png")
                chroma_key_green(raw_path, keyed_path)

                final_path = os.path.join(OUTPUT_DIR, f"{name}.png")
                standardize_size(keyed_path, final_path)
                print(f"  Finalized: {final_path} ({os.path.getsize(final_path)} bytes)")

                os.remove(raw_path)
                os.remove(keyed_path)
                break

print("\nAll files in thumbs/:")
for f in sorted(os.listdir(OUTPUT_DIR)):
    if f.endswith('.png'):
        print(f"  {f}: {os.path.getsize(os.path.join(OUTPUT_DIR, f))} bytes")
