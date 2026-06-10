"""
shuffle.py — Shuffle answer choices in Hebrew exam PDFs.

Uses PyMuPDF to render pages and detect structure.
Only the CONTENT area of each answer (left of the letter column) is
shuffled — the letter labels (א/ב/ג/ד/ה) remain in place.

Public API used by app.py:
    shuffle_exam(input_path, output_path, seed)
"""

import random
import re
import io
from pathlib import Path

import fitz                          # PyMuPDF
from PIL import Image, ImageDraw, ImageFont

# x0 threshold (PDF points) — letter labels sit at x0 ≥ this value
_LETTER_X_MIN = 528
_GARBLE_OFFSET = 0x0330
_ANSWER_LETTERS = set("אבגדה")

# ── Hebrew decoding ──────────────────────────────────────────────────────────

def _decode(text):
    """
    Decode a garbled Hebrew span from PyMuPDF.
    Chars in IPA range (U+02A0–U+02BA) are shifted +0x0330 to Hebrew Unicode,
    and each resulting Hebrew word is reversed (PDF stores RTL words LTR).
    ASCII/Latin characters pass through unchanged.
    """
    result = []
    word = []
    for ch in text:
        if 0x02A0 <= ord(ch) <= 0x02BA:
            word.append(chr(ord(ch) + _GARBLE_OFFSET))
        else:
            if word:
                result.append("".join(reversed(word)))
                word = []
            result.append(ch)
    if word:
        result.append("".join(reversed(word)))
    return "".join(result)


def _is_answer_letter(span):
    """Return True if this span is a single answer letter (א-ה)."""
    dec = _decode(span["text"]).strip(".").strip()
    return dec in _ANSWER_LETTERS and span["bbox"][0] >= _LETTER_X_MIN


# ── Structure detection ──────────────────────────────────────────────────────

def _all_spans(page):
    """Return all text spans on a page as a flat list."""
    spans = []
    for b in page.get_text("dict")["blocks"]:
        if b["type"] != 0:
            continue
        for line in b["lines"]:
            for span in line["spans"]:
                spans.append(span)
    return spans


def _parse_structure(pdf_path):
    """
    Detect question boundaries and answer letter positions.

    Returns
    -------
    questions : dict
        {q_num: {'page': int, 'slots': [{'y_top': f, 'y_bot': f}, ...]}}
        Slots are ordered א → ב → ג → ד → ה.
    code_spans : list
        [{'page': int, 'bbox': (x0,y0,x1,y1)}]  — '0000' placeholder spans.
    page_heights : list[float]
        PDF point height of each page.
    """
    doc = fitz.open(str(pdf_path))
    questions = {}
    code_spans = []
    page_heights = []

    for page_idx, page in enumerate(doc):
        page_heights.append(page.rect.height)
        spans = _all_spans(page)

        # ── '0000' code placeholder ──────────────────────────────────────────
        for span in spans:
            if re.fullmatch(r"0+", span["text"].strip()):
                code_spans.append({"page": page_idx, "bbox": span["bbox"]})

        # ── Answer letter positions ──────────────────────────────────────────
        letter_spans = [s for s in spans if _is_answer_letter(s)]
        letter_spans.sort(key=lambda s: s["bbox"][1])   # sort by y

        # ── Question header positions (look for "שאלה" word + digit nearby) ─
        q_y = {}    # {q_num: y_of_header}
        for span in spans:
            dec = _decode(span["text"]).strip()
            if "שאלה" in dec:
                y_ref = span["bbox"][1]
                for other in spans:
                    if abs(other["bbox"][1] - y_ref) < 6:
                        nums = re.findall(r"\d+", other["text"])
                        for n in nums:
                            n = int(n)
                            if 1 <= n <= 500:
                                q_y[n] = y_ref

        if not q_y or not letter_spans:
            continue

        sorted_q = sorted(q_y.items(), key=lambda x: x[1])

        for qi, (q_num, q_hdr_y) in enumerate(sorted_q):
            next_q_y = sorted_q[qi + 1][1] if qi + 1 < len(sorted_q) else page.rect.height

            # Letters belonging to this question
            q_letters = [ls for ls in letter_spans if q_hdr_y < ls["bbox"][1] < next_q_y]
            q_letters.sort(key=lambda s: s["bbox"][1])

            if len(q_letters) < 2:
                continue

            # Build slots: each slot spans from this letter's y to the next
            slots = []
            for li, ls in enumerate(q_letters):
                if li + 1 < len(q_letters):
                    y_bot = q_letters[li + 1]["bbox"][1] - 1
                else:
                    y_bot = next_q_y - 1
                slots.append({
                    "y_top": ls["bbox"][1],
                    "y_bot": y_bot,
                })

            # Cap the last slot to the typical slot height so it doesn't
            # extend all the way to the next question header.
            if len(slots) > 1:
                step = q_letters[1]["bbox"][1] - q_letters[0]["bbox"][1]
                slots[-1]["y_bot"] = min(
                    slots[-1]["y_bot"],
                    slots[-1]["y_top"] + step + 2,
                )

            questions[q_num] = {"page": page_idx, "slots": slots}

    doc.close()
    return questions, code_spans, page_heights


# ── Page rendering ───────────────────────────────────────────────────────────

def _render_pages(pdf_path, dpi=200):
    """Render all PDF pages to PIL images using PyMuPDF."""
    doc = fitz.open(str(pdf_path))
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    images = []
    for page in doc:
        pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        images.append(img)
    doc.close()
    return images


# ── Answer shuffling ─────────────────────────────────────────────────────────

def _shuffle_content(page_images, page_heights, questions, rng, dpi):
    """
    Shuffle ONLY the content area (x=0 … _LETTER_X_MIN) of each answer slot.
    Letter labels at x ≥ _LETTER_X_MIN are never touched.

    Returns modified copies of page_images.
    """
    modified = [img.copy() for img in page_images]

    for q_num in sorted(questions):
        q_info = questions[q_num]
        page_idx = q_info["page"]
        slots = q_info["slots"]

        if len(slots) < 2:
            continue

        img_ref = page_images[page_idx]
        pdf_h = page_heights[page_idx]
        scale = img_ref.size[1] / pdf_h
        letter_x_px = int(_LETTER_X_MIN * scale)

        # Crop content area for each slot
        crops = []
        for slot in slots:
            img_s = page_images[page_idx]   # same page per question
            y_top_px = max(0, int(slot["y_top"] * scale))
            y_bot_px = min(img_s.size[1], int(slot["y_bot"] * scale))
            trim = max(1, int(2 * scale))   # trim bottom edge to avoid bleed
            crop = img_s.crop((0, y_top_px, letter_x_px, y_bot_px - trim))
            crops.append({"crop": crop, "h": y_bot_px - y_top_px})

        shuffled = crops[:]
        rng.shuffle(shuffled)

        # White-out originals and paste shuffled crops
        mod_img = modified[page_idx]
        for slot, new_info in zip(slots, shuffled):
            y_top_px = max(0, int(slot["y_top"] * scale))
            y_bot_px = min(mod_img.size[1], int(slot["y_bot"] * scale))
            slot_h = y_bot_px - y_top_px

            draw = ImageDraw.Draw(mod_img)
            extra = int(4 * scale)
            draw.rectangle([(0, y_top_px), (letter_x_px, min(mod_img.size[1], y_bot_px + extra))], fill="white")

            crop = new_info["crop"]
            if crop.size[1] != slot_h and slot_h > 0:
                crop = crop.resize((letter_x_px, slot_h), Image.LANCZOS)

            mod_img.paste(crop, (0, y_top_px))

    return modified


# ── Code stamping ────────────────────────────────────────────────────────────

def _stamp_code(page_images, page_heights, code_spans, seed):
    """Replace '0000' placeholders with a deterministic 4-digit code."""
    code = str(seed % 9000 + 1000)
    result = [img.copy() for img in page_images]

    for cs in code_spans:
        page_idx = cs["page"]
        img = result[page_idx]
        img_w, img_h = img.size
        pdf_h = page_heights[page_idx]
        scale = img_h / pdf_h

        x0, y0, x1, y1 = cs["bbox"]
        px0 = max(0, int(x0 * scale) - 2)
        px1 = min(img_w, int(x1 * scale) + 2)
        py0 = max(0, int(y0 * scale) - 2)
        py1 = min(img_h, int(y1 * scale) + 2)

        draw = ImageDraw.Draw(img)
        draw.rectangle([(px0, py0), (px1, py1)], fill="white")

        box_h = py1 - py0
        font_size = max(8, int(box_h * 0.85))
        font = None
        for face in ("arial.ttf", "Arial.ttf", "DejaVuSans.ttf"):
            try:
                font = ImageFont.truetype(face, font_size)
                break
            except Exception:
                pass
        if font is None:
            font = ImageFont.load_default()

        try:
            tb = draw.textbbox((0, 0), code, font=font)
            tw, th = tb[2] - tb[0], tb[3] - tb[1]
        except Exception:
            tw, th = font_size * len(code) // 2, font_size

        tx = px0 + ((px1 - px0) - tw) // 2
        ty = py0 + ((py1 - py0) - th) // 2
        draw.text((tx, ty), code, fill="black", font=font)

    return result


# ── PDF output ───────────────────────────────────────────────────────────────

def _save_pdf(page_images, page_sizes, out_path, dpi=200):
    """Save PIL images as a multi-page PDF using PyMuPDF."""
    doc = fitz.open()
    for img, (pdf_w, pdf_h) in zip(page_images, page_sizes):
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=93)
        page = doc.new_page(width=pdf_w, height=pdf_h)
        page.insert_image(page.rect, stream=buf.getvalue())
    doc.save(str(out_path))
    doc.close()


# ── Public entry point ───────────────────────────────────────────────────────

def shuffle_exam(input_path, output_path, seed, dpi=200):
    """
    Shuffle answer choices in a Hebrew exam PDF.

    Parameters
    ----------
    input_path  : Path or str — input PDF
    output_path : Path or str — where to write the result
    seed        : int         — randomisation seed
    dpi         : int         — render resolution (default 200)

    Returns
    -------
    questions_found : int   — number of shuffled questions
    exam_code       : str   — 4-digit code stamped on the exam
    """
    input_path = Path(input_path)
    output_path = Path(output_path)
    rng = random.Random(seed)

    questions, code_spans, page_heights = _parse_structure(input_path)
    page_images = _render_pages(input_path, dpi=dpi)
    page_sizes = [(fitz.open(str(input_path))[i].rect.width,
                   fitz.open(str(input_path))[i].rect.height)
                  for i in range(len(page_images))]

    modified = _shuffle_content(page_images, page_heights, questions, rng, dpi)
    modified = _stamp_code(modified, page_heights, code_spans, seed)

    _save_pdf(modified, page_sizes, output_path, dpi)

    exam_code = str(seed % 9000 + 1000)
    return len(questions), exam_code


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse, sys
    from datetime import datetime

    parser = argparse.ArgumentParser(description="Shuffle Hebrew exam answers")
    parser.add_argument("pdf")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--out", default=None)
    parser.add_argument("--dpi", type=int, default=200)
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"Error: {pdf_path} not found", file=sys.stderr)
        sys.exit(1)

    out_dir = Path("output")
    out_dir.mkdir(exist_ok=True)
    seed = args.seed if args.seed is not None else random.randint(0, 2 ** 31)
    out = Path(args.out) if args.out else out_dir / f"shuffled_{seed}.pdf"

    print(f"Parsing + shuffling (seed={seed})…")
    n_q, code = shuffle_exam(pdf_path, out, seed, dpi=args.dpi)
    print(f"Done: {n_q} questions shuffled, exam code = {code}")
    print(f"Output: {out}")
