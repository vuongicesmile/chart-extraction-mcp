from app.services.chart_detector import detect
from app.services.pdf_parser import open_pdf, text_lines


def test_links_heading_caption_and_prose(sample_pdf):
    with open_pdf(sample_pdf) as doc:
        page = doc[0]
        [chart] = detect(page, text_lines(page))
    assert chart.context.heading == "1. Quarterly revenue"
    assert chart.context.caption == "Figure 1: Quarterly revenue comparison."
    assert chart.context.before == "Revenue includes sales from all three domestic regions."
    assert chart.context.after == "The comparison uses the same reporting basis in each quarter."
