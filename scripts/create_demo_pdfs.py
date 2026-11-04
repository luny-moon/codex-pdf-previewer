#!/usr/bin/env python3
"""Create two original vector-only PDF specimens. Requires reportlab."""
import argparse
import math
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph

ROOT = Path(__file__).resolve().parents[1]
INK = colors.HexColor('#172238')
MUTED = colors.HexColor('#52637a')
BLUE = colors.HexColor('#1d63bf')


def new_page(path, number, title, subtitle):
    pdf = canvas.Canvas(str(path), pagesize=(612, 792), invariant=1)
    pdf.setTitle(title)
    pdf.setAuthor('Codex PDF Previewer contributors')
    pdf.setSubject('Original synthetic PDF rendering specimen; no user document content')
    pdf.setFillColor(BLUE)
    pdf.setFont('Helvetica-Bold', 9)
    pdf.drawString(48, 744, f'CODEX PDF PREVIEWER / DEMO {number:02d}')
    pdf.setFillColor(INK)
    pdf.setFont('Helvetica-Bold', 25)
    pdf.drawString(48, 702, title)
    pdf.setFillColor(MUTED)
    pdf.setFont('Helvetica', 10)
    pdf.drawString(48, 680, subtitle)
    pdf.setStrokeColor(colors.HexColor('#d8e0ea'))
    pdf.line(48, 660, 564, 660)
    pdf.setFillColor(MUTED)
    pdf.setFont('Helvetica', 8)
    pdf.drawString(48, 36, 'Original demonstration content - released under the MIT license.')
    pdf.drawRightString(564, 36, f'Demo {number:02d} / 1 page')
    return pdf


def typography(path):
    pdf = new_page(path, 1, 'Type, equations & small print',
                   'Vector text at several sizes, designed for a fair rendering comparison.')
    pdf.setFillColor(INK)
    pdf.setFont('Helvetica-Bold', 13)
    pdf.drawString(48, 626, 'A reading specimen')
    for y, size in [(596, 12), (572, 10), (550, 8), (530, 7)]:
        pdf.setFont('Times-Roman', size)
        pdf.drawString(48, y, f'{size} pt  The quick brown fox jumps over the lazy dog. 0123456789')
    pdf.setFont('Helvetica-Bold', 13)
    pdf.drawString(48, 480, 'Equations and indices')
    style = ParagraphStyle('equations', fontName='Times-Roman', fontSize=17, leading=26, textColor=INK)
    lines = [
        'g(t) = (1 + t<super>2</super>) / (1 + t<super>4</super>)',
        'S<sub>n</sub> = a<sub>1</sub> + a<sub>2</sub> + ... + a<sub>n</sub>',
        'x<sub>k+1</sub> = x<sub>k</sub> + h v<sub>k</sub>',
    ]
    for y, text in zip([440, 400, 360], lines):
        paragraph = Paragraph(text, style)
        paragraph.wrap(516, 40)
        paragraph.drawOn(pdf, 48, y)
    pdf.setFont('Helvetica-Bold', 13)
    pdf.drawString(48, 300, 'Small labels and tabular numbers')
    headings = ['Sample', 'Size', 'Reference value', 'Notes']
    positions = [48, 190, 280, 410]
    pdf.setFont('Helvetica-Bold', 9)
    for x, text in zip(positions, headings):
        pdf.drawString(x, 274, text)
    for row in range(5):
        y = 249 - row * 23
        pdf.setStrokeColor(colors.HexColor('#d8e0ea'))
        pdf.setLineWidth(0.3)
        pdf.line(48, y - 7, 564, y - 7)
        pdf.setFont('Helvetica', 8)
        for x, text in zip(positions, [f'Control {row + 1:02d}', '8 pt', f'{math.pi * (row + 1):.8f}', 'Vector text']):
            pdf.drawString(x, y, text)
    pdf.setFillColor(MUTED)
    pdf.setFont('Helvetica', 9)
    pdf.drawString(48, 92, 'Use the same page, zoom and window size for both screenshots.')
    pdf.save()


def vector_detail(path):
    pdf = new_page(path, 2, 'Fine lines & chart detail',
                   'Thin strokes, dense grids and small axis labels; no embedded raster images.')
    x0, y0, width, height = 70, 352, 472, 260
    pdf.setLineWidth(0.25)
    pdf.setStrokeColor(colors.HexColor('#dbe2eb'))
    for i in range(21):
        x = x0 + width * i / 20
        pdf.line(x, y0, x, y0 + height)
    for i in range(13):
        y = y0 + height * i / 12
        pdf.line(x0, y, x0 + width, y)
    pdf.setStrokeColor(INK)
    pdf.setLineWidth(0.7)
    pdf.rect(x0, y0, width, height)
    pdf.setFillColor(MUTED)
    pdf.setFont('Helvetica', 7)
    for i in range(11):
        pdf.drawCentredString(x0 + width * i / 10, y0 - 15, f'{i / 10:.1f}')
    for i in range(7):
        pdf.drawRightString(x0 - 9, y0 + height * i / 6 - 2, f'{i / 6:.2f}')
    pdf.setFont('Helvetica', 9)
    pdf.drawCentredString(x0 + width / 2, y0 - 34, 'Normalized position')
    for color, shift, stroke in [(BLUE, 0, 0.8), (colors.HexColor('#c96037'), 0.7, 0.4)]:
        pdf.setStrokeColor(color)
        pdf.setLineWidth(stroke)
        path_curve = pdf.beginPath()
        for i in range(501):
            t = i / 500
            value = 0.5 + 0.29 * math.sin(2 * math.pi * (2 * t + shift)) * math.exp(-0.45 * t)
            point = (x0 + width * t, y0 + height * value)
            path_curve.moveTo(*point) if i == 0 else path_curve.lineTo(*point)
        pdf.drawPath(path_curve)
    pdf.setFillColor(INK)
    pdf.setFont('Helvetica-Bold', 13)
    pdf.drawString(48, 274, 'Line-width ladder')
    for i, stroke in enumerate([0.2, 0.3, 0.5, 0.75, 1.0]):
        y = 246 - 24 * i
        pdf.setFillColor(MUTED)
        pdf.setFont('Helvetica', 8)
        pdf.drawString(48, y - 3, f'{stroke:.2f} pt')
        pdf.setStrokeColor(INK)
        pdf.setLineWidth(stroke)
        pdf.line(112, y, 350, y)
        pdf.setFont('Helvetica', 7)
        pdf.drawString(370, y - 3, 'Aa Bb 0123456789')
    pdf.setFillColor(MUTED)
    pdf.setFont('Helvetica', 9)
    pdf.drawString(48, 92, 'Inspect grid intersections, thin curves and axis labels at the same zoom.')
    pdf.save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir', type=Path, default=ROOT / 'build/demo-pdfs')
    output = parser.parse_args().out_dir
    output.mkdir(parents=True, exist_ok=True)
    typography(output / 'typography-demo.pdf')
    vector_detail(output / 'vector-detail-demo.pdf')
    print('Created typography-demo.pdf and vector-detail-demo.pdf')


if __name__ == '__main__':
    main()
