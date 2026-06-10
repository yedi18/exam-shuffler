"""
shuffle.py — Shuffle answer choices in a closed-question exam PDF.

Usage:
    python shuffle.py exam.pdf [--seed N] [--out output.pdf] [--dpi 200]

- Open questions (Part A) are kept unchanged.
- Closed questions (tagged [q1]–[q10]): answer choices (tagged [a]) are shuffled.
- Images and math formulas inside answers are preserved via image-crop overlay.
"""

import argparse
import random
import re
import sys
from pathlib import Path
from datetime import datetime

import pdfplumber
from pdf2image import convert_from_path
from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas as rl_canvas
import io


PADDING = 5  # points of extra space above each answer crop


def find_poppler():
    import shutil
    import glob as _glob
    if shutil.which("pdftoppm"):
        return None
    search_roots = [
        r"C:\Program Files\poppler\bin",
        r"C:\poppler\bin",
        r"C:\tools\poppler\bin",
    ]
    # Also check winget package install location
    import os
    winget_base = os.path.expandvars(
        r"%LOCALAPPDATA%\Microsoft\WinGet\Packages"
    )
    for match in _glob.glob(os.path.join(winget_base, "*Poppler*", "**", "bin"), recursive=True):
        if Path(match, "pdftoppm.exe").exists():
            return match
    for path in search_roots:
        if Path(path, "pdftoppm.exe").exists():
            return path
    return None


def parse_markers(pdf_path):
    """
    Return (markers, page_heights).
    markers: list of dicts {type:'q'|'a', num:int|None, page:int, top:float, bottom:float}
    page_heights: list of float (PDF points), one per page
    """
    markers = []
    page_heights = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_idx, page in enumerate(pdf.pages):
            page_heights.append(page.height)
            words = page.extract_words(
                x_tolerance=5, y_tolerance=5, keep_blank_chars=True
            )
            for word in words:
                text = word["text"].strip()
                # [qN] or ]qN[ (RTL reversal)
                m = re.match(r"^[\[\]]q(\d+)[\[\]]$", text)
                if m:
                    markers.append(
                        {
                            "type": "q",
                            "num": int(m.group(1)),
                            "page": page_idx,
                            "top": word["top"],
                            "bottom": word["bottom"],
                        }
                    )
                elif text == "[a]":
                    markers.append(
                        {
                            "type": "a",
                            "num": None,
                            "page": page_idx,
                            "top": word["top"],
                            "bottom": word["bottom"],
                        }
                    )
    return markers, page_heights


def build_question_answer_slots(markers, page_heights):
    """
    Returns dict: {q_num: [slot, ...]}
    slot = {'page': int, 'y_top': float, 'y_bottom': float}
    """
    sorted_m = sorted(markers, key=lambda m: (m["page"], m["top"]))
    questions = {}
    current_q = None

    for i, marker in enumerate(sorted_m):
        if marker["type"] == "q":
            current_q = marker["num"]
            questions.setdefault(current_q, [])
        elif marker["type"] == "a" and current_q is not None:
            next_m = sorted_m[i + 1] if i + 1 < len(sorted_m) else None
            if next_m and next_m["page"] == marker["page"] and next_m["type"] == "a":
                y_bottom = next_m["top"] - PADDING
                hit_page_bottom = False
            elif next_m and next_m["page"] == marker["page"]:
                # Next marker is [q] on same page — slot may span into next question's content
                y_bottom = next_m["top"] - PADDING
                hit_page_bottom = True
            else:
                y_bottom = page_heights[marker["page"]] - PADDING
                hit_page_bottom = True

            questions[current_q].append(
                {
                    "page": marker["page"],
                    "y_top": marker["top"] - PADDING,
                    "y_bottom": y_bottom,
                    "_hit_page_bottom": hit_page_bottom,
                }
            )

    # Cap slots that extend to page bottom: limit to the max height of
    # same-question slots whose bottom was set by a real next-marker.
    for slots in questions.values():
        normal_heights = [
            s["y_bottom"] - s["y_top"]
            for s in slots if not s["_hit_page_bottom"]
        ]
        if normal_heights:
            cap = max(normal_heights)
            for slot in slots:
                if slot["_hit_page_bottom"]:
                    slot["y_bottom"] = min(
                        slot["y_bottom"], slot["y_top"] + cap
                    )
        for slot in slots:
            del slot["_hit_page_bottom"]

    return questions


def pdf_to_images(pdf_path, dpi, poppler_path):
    return convert_from_path(str(pdf_path), dpi=dpi, poppler_path=poppler_path)


def crop_slot(page_images, page_heights, slot, dpi):
    page_idx = slot["page"]
    img = page_images[page_idx]
    img_w, img_h = img.size
    pdf_h = page_heights[page_idx]
    scale = img_h / pdf_h

    y_top_px = max(0, int(slot["y_top"] * scale))
    y_bot_px = min(img_h, int(slot["y_bottom"] * scale))

    return img.crop((0, y_top_px, img_w, y_bot_px))


def shuffle_answers(page_images, page_heights, questions, seed, dpi):
    """
    For each question, crop all answer images, shuffle them,
    then white-out the original slots and paste the shuffled crops back.
    Returns modified page images (copies of originals).
    """
    rng = random.Random(seed)
    modified = [img.copy() for img in page_images]

    for q_num in sorted(questions):
        slots = questions[q_num]
        if len(slots) < 2:
            continue

        # Crop originals
        crops = [crop_slot(page_images, page_heights, s, dpi) for s in slots]

        # Shuffle
        shuffled = crops[:]
        rng.shuffle(shuffled)

        # Paste back
        for slot, crop in zip(slots, shuffled):
            page_idx = slot["page"]
            img = modified[page_idx]
            img_w, img_h = img.size
            pdf_h = page_heights[page_idx]
            scale = img_h / pdf_h

            y_top_px = max(0, int(slot["y_top"] * scale))
            y_bot_px = min(img_h, int(slot["y_bottom"] * scale))
            slot_h = y_bot_px - y_top_px
            crop_h = crop.size[1]

            # White out original slot (expand if crop is taller to prevent overflow)
            draw = ImageDraw.Draw(img)
            wipe_bot = min(img_h, max(y_bot_px, y_top_px + crop_h))
            draw.rectangle([(0, y_top_px), (img_w, wipe_bot)], fill="white")

            # Scale down only if crop is taller than slot; never scale up
            if crop_h > slot_h > 0:
                crop = crop.resize((img_w, slot_h), Image.LANCZOS)

            img.paste(crop, (0, y_top_px))

    return modified


def save_as_pdf(page_images, out_path, pdf_path, dpi):
    """
    Save the modified page images as a PDF preserving original page dimensions.
    Uses reportlab so page size matches the source PDF exactly.
    """
    with pdfplumber.open(pdf_path) as pdf:
        page_sizes = [(p.width, p.height) for p in pdf.pages]

    c = rl_canvas.Canvas(str(out_path))
    for i, (img, (pdf_w, pdf_h)) in enumerate(zip(page_images, page_sizes)):
        c.setPageSize((pdf_w, pdf_h))
        # Convert PIL image to bytes
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=92, dpi=(dpi, dpi))
        buf.seek(0)
        c.drawImage(
            rl_canvas.ImageReader(buf),
            0, 0,
            width=pdf_w,
            height=pdf_h,
            preserveAspectRatio=False,
        )
        c.showPage()
    c.save()


def main():
    parser = argparse.ArgumentParser(
        description="Shuffle closed-question answer choices in an exam PDF"
    )
    parser.add_argument("pdf", help="Input exam PDF")
    parser.add_argument("--seed", type=int, default=None, help="Random seed (default: random)")
    parser.add_argument("--out", default=None, help="Output PDF path")
    parser.add_argument("--dpi", type=int, default=200, help="Render resolution (default: 200)")
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"Error: file not found: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    out_dir = Path("output")
    out_dir.mkdir(exist_ok=True)

    if args.out:
        out_path = Path(args.out)
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = out_dir / f"shuffled_{ts}.pdf"

    poppler_path = find_poppler()

    print("Parsing PDF structure...")
    markers, page_heights = parse_markers(pdf_path)
    questions = build_question_answer_slots(markers, page_heights)

    q_nums = sorted(questions)
    print(f"Found {len(q_nums)} closed question(s): {q_nums}")
    for n in q_nums:
        print(f"  Q{n}: {len(questions[n])} answer choices")

    print(f"\nConverting {len(page_heights)} pages to images at {args.dpi} DPI...")
    page_images = pdf_to_images(pdf_path, dpi=args.dpi, poppler_path=poppler_path)

    seed = args.seed if args.seed is not None else random.randint(0, 2**31)
    print(f"Shuffling answers (seed={seed})...")
    modified = shuffle_answers(page_images, page_heights, questions, seed, args.dpi)

    print(f"Saving to {out_path}...")
    save_as_pdf(modified, out_path, pdf_path, args.dpi)
    print(f"\nDone!  {out_path}")
    print(f"Seed used: {seed}  (pass --seed {seed} to reproduce this shuffle)")


if __name__ == "__main__":
    main()
