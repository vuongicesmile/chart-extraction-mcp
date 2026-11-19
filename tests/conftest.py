import pymupdf
import pytest


def bar_pdf(values=(25, 50, 75), *, printed=True, raster=False, empty_first=False):
    with pymupdf.open() as doc:
        if empty_first:
            doc.new_page().insert_text((40, 50), "Cover page")
        page = doc.new_page(width=620, height=530)
        page.insert_text((100, 68), "1. Quarterly revenue", fontsize=18, fontname="hebo")
        page.insert_text((100, 102), "Revenue includes sales from all three domestic regions.")
        page.insert_text((216, 168), "Revenue by quarter", fontsize=16)
        page.draw_line((170, 198), (170, 360))
        page.draw_line((170, 360), (442, 360))
        page.insert_text((114, 320), "Revenue (USD)", rotate=90)
        for tick in (0, 25, 50, 75, 100):
            page.insert_text((142, 364 - tick * 1.6), str(tick), fontsize=9)
        for index, value in enumerate(values):
            middle = 220 + index * 87
            top = 360 - value * 1.6
            page.draw_rect((middle - 18, top, middle + 18, 360), fill=(0.13, 0.36, 0.69))
            page.insert_text((middle - 7, 378), f"Q{index + 1}", fontsize=12)
            if printed:
                page.insert_text((middle - 6, top - 6), str(value), fontsize=12)
        page.insert_text((282, 401), "Quarter", fontsize=10)
        page.insert_text((170, 430), "Figure 1: Quarterly revenue comparison.", fontsize=11)
        page.insert_text(
            (170, 461), "The comparison uses the same reporting basis in each quarter."
        )
        if raster:
            region = pymupdf.Rect(94, 138, 465, 414)
            picture = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), clip=region).tobytes("png")
            with pymupdf.open() as converted:
                image_page = converted.new_page(width=620, height=530)
                image_page.insert_image(region, stream=picture)
                image_page.insert_text((170, 430), "Figure 1: Quarterly revenue comparison.")
                return converted.tobytes()
        return doc.tobytes()


@pytest.fixture
def sample_pdf():
    return bar_pdf()
