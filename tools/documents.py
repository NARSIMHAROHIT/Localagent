from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem

from .files import _resolve          # reuse the sandbox check
from .registry import tool

STYLES = getSampleStyleSheet()


@tool
def write_pdf(path: str, title: str, content: str) -> str:
    """Save text as a PDF file in the workspace. Write the content in simple
    markdown: '# ' for a heading, '- ' for a bullet, and blank lines between
    paragraphs.

    Args:
        path: Where to save it, for example "reports/summary.pdf".
        title: The title shown at the top of the first page.
        content: The body text, in simple markdown.
    """
    target = _resolve(path)
    if target.suffix.lower() != ".pdf":
        target = target.with_suffix(".pdf")
    target.parent.mkdir(parents=True, exist_ok=True)

    story = [Paragraph(title, STYLES["Title"]), Spacer(1, 0.2 * inch)]
    bullets = []

    def flush_bullets():
        if bullets:
            story.append(ListFlowable(
                [ListItem(Paragraph(b, STYLES["BodyText"])) for b in bullets],
                bulletType="bullet",
            ))
            story.append(Spacer(1, 0.1 * inch))
            bullets.clear()

    for raw in content.splitlines():
        line = raw.strip()
        if not line:
            flush_bullets()
            story.append(Spacer(1, 0.1 * inch))
        elif line.startswith("### "):
            flush_bullets()
            story.append(Paragraph(line[4:], STYLES["Heading3"]))
        elif line.startswith("## "):
            flush_bullets()
            story.append(Paragraph(line[3:], STYLES["Heading2"]))
        elif line.startswith("# "):
            flush_bullets()
            story.append(Paragraph(line[2:], STYLES["Heading1"]))
        elif line.startswith(("- ", "* ")):
            bullets.append(line[2:])
        else:
            flush_bullets()
            story.append(Paragraph(line, STYLES["BodyText"]))
    flush_bullets()

    SimpleDocTemplate(
        str(target), pagesize=LETTER,
        leftMargin=0.9 * inch, rightMargin=0.9 * inch,
        topMargin=0.9 * inch, bottomMargin=0.9 * inch,
        title=title,
    ).build(story)

    size = target.stat().st_size
    return f"Saved PDF to '{path}' ({size} bytes)."