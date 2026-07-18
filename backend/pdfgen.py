"""CV PDF export via fpdf2 — deliberately plain typographic layout (near-ATS):
single column, strong hierarchy, no graphics. Content is the structured CV JSON."""
from fpdf import FPDF

MARGIN = 16


class _CV(FPDF):
    def header(self):
        pass  # no running header — the name block is set once by render


def _latin(text: str) -> str:
    """Core fonts are latin-1; degrade exotic glyphs instead of crashing."""
    return str(text).encode("latin-1", "replace").decode("latin-1")


def render_cv_pdf(cv: dict, profile: dict) -> bytes:
    pdf = _CV(format="A4")
    pdf.set_auto_page_break(auto=True, margin=MARGIN)
    pdf.set_margins(MARGIN, MARGIN, MARGIN)
    pdf.add_page()
    w = pdf.w - 2 * MARGIN

    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(w, 9, _latin(profile.get("full_name", "")), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10.5)
    pdf.set_text_color(70, 70, 70)
    headline = cv.get("headline") or profile.get("headline", "")
    pdf.cell(w, 5.5, _latin(headline), new_x="LMARGIN", new_y="NEXT")
    contact = " · ".join(x for x in [profile.get("location", "")]
                         + [l.get("url", "") for l in profile.get("links", [])] if x)
    if contact:
        pdf.cell(w, 5.5, _latin(contact), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(2)

    def section(title: str):
        pdf.ln(2)
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(w, 6, _latin(title.upper()), new_x="LMARGIN", new_y="NEXT")
        pdf.set_draw_color(180, 180, 180)
        pdf.line(MARGIN, pdf.get_y(), pdf.w - MARGIN, pdf.get_y())
        pdf.ln(1.5)

    if cv.get("summary"):
        section("Summary")
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(w, 5, _latin(cv["summary"]))

    if cv.get("skills"):
        section("Skills")
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(w, 5, _latin(" · ".join(cv["skills"])))

    if cv.get("experience"):
        section("Experience")
        for exp in cv["experience"]:
            pdf.set_font("Helvetica", "B", 10.5)
            title_line = f"{exp.get('title', '')} — {exp.get('org', '')}"
            if exp.get("verified"):
                title_line += "  [onchain-verified]"
            pdf.cell(w * 0.72, 5.5, _latin(title_line))
            pdf.set_font("Helvetica", "", 9.5)
            pdf.set_text_color(90, 90, 90)
            pdf.cell(w * 0.28, 5.5, _latin(f"{exp.get('start', '')} – {exp.get('end', '')}"),
                     align="R", new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)
            pdf.set_font("Helvetica", "", 10)
            for b in exp.get("bullets", []):
                pdf.set_x(MARGIN + 4)
                pdf.multi_cell(w - 4, 5, _latin(f"• {b}"))
            pdf.ln(1)

    if cv.get("education"):
        section("Education")
        pdf.set_font("Helvetica", "", 10)
        for ed in cv["education"]:
            pdf.cell(w, 5.5, _latin(f"{ed.get('degree', '')} — {ed.get('school', '')} "
                                    f"({ed.get('year', '')})"), new_x="LMARGIN", new_y="NEXT")

    return bytes(pdf.output())
