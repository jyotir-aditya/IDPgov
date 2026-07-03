"""Prompt text + Gemini response schema for Hindi letter extraction.

Design: the prompt is split into three sections —
  1. Document understanding (layout regions + govt-letter template)
  2. Field-specific extraction algorithms (explicit priority + rejection rules)
  3. Output contract (rich candidates with position/label/raw_text, confidence rubric)

The schema enforces structured JSON output so there's no parsing fragility.
Positions are a closed enum — models are far more consistent choosing from a
small vocabulary than producing free-form location descriptions.
"""
from __future__ import annotations

POSITIONS = [
    "TOP_LEFT",
    "TOP_CENTER",
    "TOP_RIGHT",
    "BODY",
    "BOTTOM_LEFT",
    "BOTTOM_CENTER",
    "BOTTOM_RIGHT",
    "UNKNOWN",
]

_CANDIDATE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "value": {"type": "STRING", "description": "Normalized value"},
        "raw_text": {"type": "STRING", "description": "Exact text as it appears on the document"},
        "position": {"type": "STRING", "enum": POSITIONS},
        "label": {"type": "STRING", "description": "Nearby label on the document, e.g. पत्रांक, दिनांक, विषय"},
        "reason": {"type": "STRING"},
        "confidence": {"type": "NUMBER"},
    },
    "required": ["value", "position", "reason"],
}

_SELECTED_SCHEMA = {
    "type": "OBJECT",
    "description": "Metadata of the candidate chosen as the final value",
    "properties": {
        "position": {"type": "STRING", "enum": POSITIONS},
        "label": {"type": "STRING"},
        "raw_text": {"type": "STRING"},
        "reason": {"type": "STRING"},
    },
    "required": ["position", "reason"],
}


def _field_schema(value_desc: str) -> dict:
    return {
        "type": "OBJECT",
        "properties": {
            "value": {"type": "STRING", "description": value_desc},
            "confidence": {"type": "NUMBER"},
            "selected_candidate": _SELECTED_SCHEMA,
            "candidates": {"type": "ARRAY", "items": _CANDIDATE_SCHEMA},
        },
        "required": ["value", "confidence", "selected_candidate", "candidates"],
    }


RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "ocr_text": {
            "type": "STRING",
            "description": "Full verbatim transcription in Devanagari, preserving layout, handwritten text and stamps.",
        },
        "fields": {
            "type": "OBJECT",
            "properties": {
                "letter_number": _field_schema("Official dispatch number of THIS letter"),
                "letter_date": _field_schema("Official letter date in DD-MM-YYYY, or empty string if not found"),
                "subject": _field_schema("Complete subject line, verbatim if विषय line exists"),
                "received_from": _field_schema("Sender name + designation from signature block"),
            },
            "required": ["letter_number", "letter_date", "subject", "received_from"],
        },
        "overall_confidence": {"type": "NUMBER"},
        "notes": {"type": "STRING"},
    },
    "required": ["ocr_text", "fields", "overall_confidence"],
}


PROMPT_TEXT = """You are a deterministic document parser for Hindi government letters (हिंदी सरकारी पत्र). You do not guess casually — you locate candidates, rank them by explicit rules, and report evidence for every choice.

═══════════════════════════════════════
SECTION 1 — DOCUMENT UNDERSTANDING (do this BEFORE extracting any field)
═══════════════════════════════════════

ORIENTATION: the input is a phone photo or scan and may be ROTATED (sideways or upside down). First determine the correct reading orientation of the letter. All region names below refer to the letter in its CORRECT reading orientation, not the photo's orientation.

Then analyze the layout of every page. Mentally divide each page into these regions and use ONLY these region names everywhere in your output:

  TOP_LEFT · TOP_CENTER · TOP_RIGHT
  BODY
  BOTTOM_LEFT · BOTTOM_CENTER · BOTTOM_RIGHT
  UNKNOWN

Typical Hindi government letter layout (guidance only — actual document evidence always wins):

  TOP_LEFT / TOP_CENTER : department / office name (विभाग, कार्यालय)
  TOP_CENTER            : heading, letter type (कार्यालय आदेश, अधिसूचना, परिपत्र)
  TOP_LEFT / TOP_CENTER : official number line, e.g. "संख्या-01/माशि०/स्था०'ख'-68/2024/____" — the trailing part after the last "/" is often HANDWRITTEN or left blank
  TOP_RIGHT             : issue date line, e.g. "पटना, दिनांक ____" — digits often HANDWRITTEN
  BODY                  : letter content — contains DISTRACTING references to OTHER letters (their ज्ञापांक/पत्रांक and dates) that are NOT this letter's own number/date
  BOTTOM_RIGHT          : signature block — name and designation (पदनाम), designation often in parentheses or on the line below the name
  BOTTOM_CENTER / BOTTOM_LEFT : official dispatch section — a line like "ज्ञापांक-01/.../2024/1061, पटना, दिनांक ..." where the trailing serial (e.g. 1061) and the date are HANDWRITTEN. Followed by प्रतिलिपि (copy-to) list.
  Multi-page letters    : the dispatch section and signature are usually on the LAST page

RECEIPT ANNOTATIONS (very important): after a letter arrives, the RECEIVING office adds its own marks — a received/inward stamp (often with "No.___" and a date), and handwritten numbers and dates scribbled diagonally in the margins (e.g. an inward register number like "2239" and received dates like "23/6/26", "24/6/26"). These belong to the RECEIVER, not to the letter. They are NEVER the letter's own number or date. Transcribe them in ocr_text, list them as rejected candidates, but never select them.

Terminology:
  पत्रांक / ज्ञापांक / संख्या = dispatch number of THIS letter
  दिनांक / तिथि = date · विषय = subject
  सेवा में = addressee (recipient, NOT sender) · प्रतिलिपि = copy-to list (NOT sender)
  आवक / प्राप्ति / received stamp = receiving office's inward marks (NOT this letter's fields)

═══════════════════════════════════════
SECTION 2 — FIELD EXTRACTION ALGORITHMS
═══════════════════════════════════════

For EVERY field, follow this algorithm internally. Do not skip steps. Do not output the reasoning itself — only the final JSON.

  STEP 1: Locate EVERY possible value on all pages.
  STEP 2: For each, record: value, region (position), nearby label, exact raw text.
  STEP 3: Rank them using the field's priority rules below.
  STEP 4: Select the best one as `value` and describe it in `selected_candidate`.
  STEP 5: Return ALL located candidates in `candidates` (including the selected one), each with its own reason and confidence.

── letter_number (पत्रांक) ──
Priority order:
  1. BOTTOM_CENTER / BOTTOM_LEFT — the dispatch line labelled ज्ञापांक / पत्रांक / संख्या
  2. BOTTOM_RIGHT (near signature)
  3. Header number line (TOP_LEFT / TOP_CENTER, labelled संख्या)
Dispatch lines are often a long office file code ending in a handwritten serial, e.g. "ज्ञापांक-01/माशि०/स्था०'ख'-68/2024/1061" — the TRAILING handwritten serial (1061) is the dispatch number; select it as `value` and put the full code in `raw_text`. The full code may also be listed as a separate candidate.
If both a handwritten and a printed number exist near the bottom, prefer the HANDWRITTEN one — it is the dispatch number stamped when the letter was sent.
REJECT (never select, but list as candidates with a reason):
  - receipt/inward register numbers — handwritten diagonally in margins or inside/near a received stamp (see RECEIPT ANNOTATIONS)
  - numbers of OTHER letters cited inside BODY paragraphs (e.g. "आपके पत्रांक ... के संदर्भ में", "विभागीय आदेश ज्ञापांक-569")
  - file numbers, paragraph/serial numbering, department codes in letterhead
If multiple remain, choose the one in the official dispatch section of the LAST page.

── letter_date (तिथि) ──
STEP 1 is MANDATORY here: locate EVERY date visible anywhere on the document — header issue date, dispatch-line date, dates inside the body/subject, receipt dates in margins and stamps — and return EACH ONE as a candidate with its position, label and raw_text. A typical letter photo contains 3–5 distinct dates; returning only one candidate means you skipped Step 1.
Priority order for selection:
  1. The date immediately adjacent to the SELECTED letter_number (dispatch line, usually bottom, often handwritten)
  2. The issue date on the header line "पटना, दिनांक ..." / "दिनांक ..." (TOP_RIGHT)
These two are usually the SAME date. If they differ and the handwriting is ambiguous, keep both as strong candidates and lower the selected confidence.
NEVER select:
  - receipt/inward dates handwritten diagonally in margins or in a received stamp (see RECEIPT ANNOTATIONS)
  - dates inside the BODY or subject line (event dates, effective-from/to dates like "दिनांक-22.06.2026 से", references to other letters' dates)
DD and MM may be handwritten while the year is printed — read them together as one date. Handwritten digits are easy to misread (1↔2, 9↔3): transcribe the strokes exactly in raw_text and reflect uncertainty in confidence.
Validation — the final value MUST satisfy: DD between 01–31, MM between 01–12, YYYY four digits. Output format: DD-MM-YYYY.
If no valid official date is found: value = "" and confidence = 0.0. NEVER invent digits. If a digit is illegible, do not guess the whole date up — lower confidence and note it.

── subject (विषय) ──
Priority order:
  1. A line starting with "विषय:" / "विषय:-" / "विषय -" → copy VERBATIM and COMPLETE (it may span multiple lines — never truncate)
  2. "पत्र का विषय"
  3. "Subject:"
  4. Document heading
  5. Infer from the opening paragraph (confidence ≤ 0.6)

── received_from (प्रेषक) ──
Look for the signature block. Priority order:
  1. BOTTOM_RIGHT signature block
  2. BOTTOM_CENTER
  3. Final signature block at the end of the document (last page)
If multiple signatures exist, choose the BOTTOM-MOST one.
Combine: name + designation (designation is often in parentheses or on the line under the name). Format: "नाम, पदनाम".
REJECT: the addressee under सेवा में, and everyone in the प्रतिलिपि (copy-to) list.

═══════════════════════════════════════
SECTION 3 — OUTPUT CONTRACT
═══════════════════════════════════════

── ocr_text ──
Full verbatim transcription of every page in Devanagari.
Preserve: line breaks, headings, spacing/structure, tables, signature blocks, stamps, and ALL handwritten additions.
Do NOT summarize. Do NOT correct grammar. Do NOT omit stamps or handwritten text.
If something is unreadable, write [UNREADABLE] in its place.

── candidates ──
Every candidate object must contain:
  value      — normalized value (dates as DD-MM-YYYY; if Devanagari digits appear, convert them here)
  raw_text   — the EXACT text as written on the document (keep original digits/spelling)
  position   — one of the region names from Section 1, nothing else
  label      — the label printed next to it on the document (पत्रांक, दिनांक, विषय …), or "" if none
  reason     — one short sentence: why this is / is not the official value
  confidence — per the rubric below
`selected_candidate` repeats the position/label/raw_text/reason of the candidate you chose as `value`.
Always return at least one candidate per field when anything was found; return ALL plausible candidates, not just the winner.

── confidence rubric (use these anchors, per field) ──
  1.0  printed, perfectly readable
  0.9  printed, minor ambiguity
  0.8  handwritten, clearly readable
  0.6  partially readable
  0.4  informed guess (e.g. subject inferred from paragraph)
  0.2  very uncertain
  0.0  not found

── overall_confidence ── average of the four field confidences.
── notes ── anomalies worth flagging (e.g. "पत्रांक हस्तलिखित और अस्पष्ट", "दो हस्ताक्षर मिले, निचला चुना").

═══════════════════════════════════════
EXAMPLE OUTPUT (shape reference)
═══════════════════════════════════════
{
  "ocr_text": "कार्यालय आदेश\\nविषय: ग्रीष्मकाल में राज्य में पड़ने वाली भीषण गर्मी...\\n...\\nसज्जन आर०\\n(निदेशक, माध्यमिक शिक्षा)\\nपत्रांक- 1061          दिनांक- 23/06/2026",
  "fields": {
    "letter_number": {
      "value": "1061",
      "confidence": 0.8,
      "selected_candidate": {
        "position": "BOTTOM_CENTER",
        "label": "पत्रांक",
        "raw_text": "पत्रांक- 1061",
        "reason": "Handwritten dispatch number in the official dispatch section at the bottom"
      },
      "candidates": [
        {
          "value": "1061",
          "raw_text": "पत्रांक- 1061",
          "position": "BOTTOM_CENTER",
          "label": "पत्रांक",
          "reason": "Handwritten dispatch number in the official dispatch section",
          "confidence": 0.8
        },
        {
          "value": "68/2024",
          "raw_text": "पत्र संख्या 68/2024 के संदर्भ में",
          "position": "BODY",
          "label": "",
          "reason": "Reference to another letter inside a body paragraph — rejected",
          "confidence": 0.2
        }
      ]
    },
    "letter_date": {
      "value": "23-06-2026",
      "confidence": 0.8,
      "selected_candidate": {
        "position": "BOTTOM_CENTER",
        "label": "दिनांक",
        "raw_text": "दिनांक- 23/06/2026",
        "reason": "Adjacent to the selected dispatch number"
      },
      "candidates": [
        {
          "value": "23-06-2026",
          "raw_text": "दिनांक- 23/06/2026",
          "position": "BOTTOM_CENTER",
          "label": "दिनांक",
          "reason": "Adjacent to dispatch number",
          "confidence": 0.8
        },
        {
          "value": "22-06-2026",
          "raw_text": "दिनांक-22.06.2026 से",
          "position": "BODY",
          "label": "",
          "reason": "Event date inside the subject line — rejected",
          "confidence": 0.2
        },
        {
          "value": "24-06-2026",
          "raw_text": "24/6/26",
          "position": "BOTTOM_LEFT",
          "label": "",
          "reason": "Receipt date handwritten diagonally in the margin by the receiving office — rejected",
          "confidence": 0.2
        }
      ]
    },
    "subject": {
      "value": "ग्रीष्मकाल में राज्य में पड़ने वाली भीषण गर्मी एवं लू को ध्यान में रखते हुए ... (कार्यालय आदेश)",
      "confidence": 0.95,
      "selected_candidate": {
        "position": "TOP_CENTER",
        "label": "विषय",
        "raw_text": "विषय: ग्रीष्मकाल में ...",
        "reason": "Explicit विषय line, copied verbatim"
      },
      "candidates": [
        {
          "value": "ग्रीष्मकाल में राज्य में पड़ने वाली भीषण गर्मी एवं लू को ध्यान में रखते हुए ... (कार्यालय आदेश)",
          "raw_text": "विषय: ग्रीष्मकाल में ...",
          "position": "TOP_CENTER",
          "label": "विषय",
          "reason": "Explicit विषय line",
          "confidence": 0.95
        }
      ]
    },
    "received_from": {
      "value": "सज्जन आर०, निदेशक (माध्यमिक शिक्षा)",
      "confidence": 0.9,
      "selected_candidate": {
        "position": "BOTTOM_RIGHT",
        "label": "",
        "raw_text": "सज्जन आर०\\n(निदेशक, माध्यमिक शिक्षा)",
        "reason": "Bottom-most signature block; designation in parentheses under the name"
      },
      "candidates": [
        {
          "value": "सज्जन आर०, निदेशक (माध्यमिक शिक्षा)",
          "raw_text": "सज्जन आर०\\n(निदेशक, माध्यमिक शिक्षा)",
          "position": "BOTTOM_RIGHT",
          "label": "",
          "reason": "Bottom-most signature block",
          "confidence": 0.9
        }
      ]
    }
  },
  "overall_confidence": 0.86,
  "notes": "पत्रांक और तिथि हस्तलिखित हैं।"
}
"""
