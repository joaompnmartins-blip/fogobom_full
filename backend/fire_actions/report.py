"""
Geração do Plano Operacional de Queima em .docx
Conversão do generate_bp_report.js original para python-docx.
"""
import io
import json
import math
from datetime import date
from PIL import Image, ImageDraw, ImageFont

from docx import Document
from fire_actions.models import BurningPlan
from docx.shared import Pt, Cm, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.oxml.ns import qn
from docx.oxml import OxmlElement


# ── Palette ───────────────────────────────────────────────────────────────────
BRAND  = RGBColor(0xD0, 0x5C, 0x1E)   # orange
GREY   = RGBColor(0xF5, 0xF5, 0xF5)
WHITE  = RGBColor(0xFF, 0xFF, 0xFF)
DIM    = RGBColor(0x88, 0x88, 0x88)
BORDER = RGBColor(0xCC, 0xCC, 0xCC)


def _val(s, fallback='—'):
    if s is None or str(s).strip() in ('', 'None'):
        return fallback
    return str(s).strip()


def _set_cell_bg(cell, hex_color: str):
    """Set cell background shading."""
    tc   = cell._tc
    tcPr = tc.get_or_add_tcPr()
    shd  = OxmlElement('w:shd')
    shd.set(qn('w:val'),   'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'),  hex_color)
    tcPr.append(shd)


def _set_cell_borders(cell):
    tc   = cell._tc
    tcPr = tc.get_or_add_tcPr()
    borders = OxmlElement('w:tcBorders')
    for side in ('top', 'left', 'bottom', 'right'):
        el = OxmlElement(f'w:{side}')
        el.set(qn('w:val'),   'single')
        el.set(qn('w:sz'),    '4')
        el.set(qn('w:color'), 'CCCCCC')
        borders.append(el)
    tcPr.append(borders)


def _label_cell(table_cell, text):
    _set_cell_bg(table_cell, 'F5F5F5')
    _set_cell_borders(table_cell)
    p = table_cell.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    run = p.add_run(text)
    run.bold      = True
    run.font.size = Pt(9)
    run.font.name = 'Arial'


def _value_cell(table_cell, text):
    _set_cell_borders(table_cell)
    p = table_cell.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    run = p.add_run(_val(text))
    run.font.size = Pt(9)
    run.font.name = 'Arial'


def _section_heading(doc, text):
    p   = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(16)
    p.paragraph_format.space_after  = Pt(4)
    # Bottom border
    pPr  = p._p.get_or_add_pPr()
    pBdr = OxmlElement('w:pBdr')
    bot  = OxmlElement('w:bottom')
    bot.set(qn('w:val'),   'single')
    bot.set(qn('w:sz'),    '12')
    bot.set(qn('w:color'), 'D05C1E')
    pBdr.append(bot)
    pPr.append(pBdr)
    run = p.add_run(text)
    run.bold       = True
    run.font.size  = Pt(13)
    run.font.color.rgb = BRAND
    run.font.name  = 'Arial'
    return p


def _two_col_table(doc, pairs):
    """pairs = list of ((label1, val1), (label2, val2))"""
    table = doc.add_table(rows=len(pairs), cols=4)
    table.style = 'Table Grid'
    col_w = Cm(4.5)
    for i, ((l1, v1), (l2, v2)) in enumerate(pairs):
        row = table.rows[i]
        for cell in row.cells:
            cell.width = col_w
        _label_cell(row.cells[0], l1)
        _value_cell(row.cells[1], v1)
        _label_cell(row.cells[2], l2)
        _value_cell(row.cells[3], v2)
    doc.add_paragraph()



def _generate_parcela_schema(bp, width=900, height=600, padding=60) -> io.BytesIO | None:
    """
    Render a clean white PNG with the parcela boundary drawn in orange.
    Uses only Pillow — no external geo libs required beyond what Django/GeoDjango provides.
    Returns a BytesIO with the PNG, or None if no geometry available.
    """
    # Collect all polygon coordinate rings from all linked parcelas
    all_coords = []
    for parcel in bp.pre_plan.parcels.all():
        if not parcel.geometry:
            continue
        try:
            geom_json = json.loads(parcel.geometry.json)
            gtype = geom_json.get('type', '')
            if gtype == 'Polygon':
                rings = geom_json['coordinates']
            elif gtype == 'MultiPolygon':
                rings = [ring for poly in geom_json['coordinates'] for ring in poly]
            else:
                continue
            for ring in rings:
                all_coords.extend(ring)
        except Exception:
            continue

    if not all_coords:
        return None

    # Bounding box in geographic coords
    lngs = [c[0] for c in all_coords]
    lats = [c[1] for c in all_coords]
    min_lng, max_lng = min(lngs), max(lngs)
    min_lat, max_lat = min(lats), max(lats)

    # Scale to image with padding, flip Y (lat increases upward, pixels downward)
    draw_w = width  - 2 * padding
    draw_h = height - 2 * padding
    lng_range = max_lng - min_lng or 1e-6
    lat_range = max_lat - min_lat or 1e-6

    # Keep aspect ratio
    scale = min(draw_w / lng_range, draw_h / lat_range)
    offset_x = padding + (draw_w - lng_range * scale) / 2
    offset_y = padding + (draw_h - lat_range * scale) / 2

    def to_px(lng, lat):
        x = offset_x + (lng - min_lng) * scale
        y = height - (offset_y + (lat - min_lat) * scale)  # flip Y
        return (int(round(x)), int(round(y)))

    img  = Image.new('RGB', (width, height), color='white')
    draw = ImageDraw.Draw(img)

    # Draw thin grid lines
    for i in range(5):
        gx = padding + i * draw_w // 4
        gy = padding + i * draw_h // 4
        draw.line([(gx, padding), (gx, height - padding)], fill='#e0e0e0', width=1)
        draw.line([(padding, gy), (width - padding, gy)], fill='#e0e0e0', width=1)

    # Draw each ring
    for parcel in bp.pre_plan.parcels.all():
        if not parcel.geometry:
            continue
        try:
            geom_json = json.loads(parcel.geometry.json)
            gtype = geom_json.get('type', '')
            polys = geom_json['coordinates'] if gtype == 'Polygon' else                     [poly for poly in geom_json['coordinates']] if gtype == 'MultiPolygon' else []

            if gtype == 'Polygon':
                polys = [geom_json['coordinates']]

            for poly in polys:
                for ring in poly:
                    pts = [to_px(c[0], c[1]) for c in ring]
                    if len(pts) < 2:
                        continue
                    # Filled polygon with light orange fill
                    draw.polygon(pts, fill='#fff3ec', outline=None)
                    # Border — draw thick then thin for crisp look
                    draw.line(pts + [pts[0]], fill='#D05C1E', width=3)

            # Parcel name label at centroid
            cx = sum(c[0] for c in poly[0]) / len(poly[0])
            cy = sum(c[1] for c in poly[0]) / len(poly[0])
            px, py = to_px(cx, cy)
            label = parcel.name
            try:
                font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 14)
            except Exception:
                font = ImageFont.load_default()
            bbox = draw.textbbox((0, 0), label, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            draw.rectangle([px - tw//2 - 4, py - th//2 - 3, px + tw//2 + 4, py + th//2 + 3],
                           fill='white', outline='#D05C1E', width=1)
            draw.text((px - tw//2, py - th//2), label, fill='#D05C1E', font=font)
        except Exception:
            continue

    # Outer border
    draw.rectangle([padding//2, padding//2, width - padding//2, height - padding//2],
                   outline='#cccccc', width=1)

    # Scale bar (approximate, degrees → km rough conversion at Algarve lat ~37°)
    DEG_KM = 111.32 * math.cos(math.radians(37))  # km per degree longitude
    bar_deg = 0.01  # 0.01° longitude
    bar_km  = round(bar_deg * DEG_KM * 1000)  # metres
    bar_px  = int(bar_deg * scale)
    bx, by  = padding, height - padding//2 + 8
    draw.line([(bx, by), (bx + bar_px, by)], fill='#444', width=2)
    draw.line([(bx, by - 3), (bx, by + 3)], fill='#444', width=2)
    draw.line([(bx + bar_px, by - 3), (bx + bar_px, by + 3)], fill='#444', width=2)
    try:
        sfont = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 11)
    except Exception:
        sfont = ImageFont.load_default()
    draw.text((bx, by + 5), f'≈ {bar_km} m', fill='#444', font=sfont)

    buf = io.BytesIO()
    img.save(buf, format='PNG', dpi=(150, 150))
    buf.seek(0)
    return buf


def generate_bp_docx(bp) -> bytes:
    """
    Given a BurningPlan instance, return the .docx as bytes.
    """
    doc = Document()

    # ── Page margins ─────────────────────────────────────────────────────────
    for section in doc.sections:
        section.top_margin    = Cm(2)
        section.bottom_margin = Cm(2)
        section.left_margin   = Cm(2.5)
        section.right_margin  = Cm(2.5)

    # ── Title ─────────────────────────────────────────────────────────────────
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    tr = title.add_run('PLANO OPERACIONAL DE QUEIMA')
    tr.bold           = True
    tr.font.size      = Pt(20)
    tr.font.color.rgb = BRAND
    tr.font.name      = 'Arial'

    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sr = sub.add_run(f'Relatório #{bp.pk}  ·  '
                     f'Gerado em {date.today().strftime("%d/%m/%Y")}')
    sr.font.size      = Pt(9)
    sr.font.color.rgb = DIM
    sr.font.name      = 'Arial'
    doc.add_paragraph()

    # ── 1. Identificação ──────────────────────────────────────────────────────
    _section_heading(doc, '1. Identificação')
    t = doc.add_table(rows=4, cols=2)
    t.style = 'Table Grid'
    parcel_names = ', '.join(p.name for p in bp.pre_plan.parcels.all()) or '—'
    rows_data = [
        ('Pré-Plano associado', bp.pre_plan.name),
        ('Parcela(s)',          parcel_names),
        ('Responsável',         bp.pre_plan.responsible),
        ('Data de Execução',    str(bp.execution_date)),
    ]
    for i, (label, value) in enumerate(rows_data):
        _label_cell(t.rows[i].cells[0], label)
        _value_cell(t.rows[i].cells[1], value)
    doc.add_paragraph()

    # ── 2. Equipa e Meios ─────────────────────────────────────────────────────
    _section_heading(doc, '2. Equipa e Meios')
    try:
        vd = json.loads(bp.vehicles or '{}')
    except Exception:
        vd = {}
    op_names = ', '.join(o.name for o in bp.operatives.all()) or '—'
    _two_col_table(doc, [
        (('Nº de Homens',    bp.num_men),   ('Operacionais', op_names)),
        (('VFCI',            vd.get('VFCI', 0)), ('VLCI', vd.get('VLCI', vd.get('VFCM', 0)))),
        (('Outros veículos', vd.get('Outro', '—')), ('', '')),
    ])

    # ── 3. Problemas ──────────────────────────────────────────────────────────
    _section_heading(doc, '3. Problemas Identificados')
    t = doc.add_table(rows=1, cols=1)
    t.style = 'Table Grid'
    _value_cell(t.rows[0].cells[0], bp.problems or 'Nenhum problema identificado.')
    doc.add_paragraph()

    # ── 4. Humidade dos Combustíveis ──────────────────────────────────────────
    _section_heading(doc, '4. Humidade dos Combustíveis')
    _two_col_table(doc, [
        (('Superficial (%)',   bp.fuel_superficial), ('Manta morta F (%)', bp.fuel_manta_f)),
        (('Manta morta H (%)', bp.fuel_manta_h),     ('', '')),
    ])

    # ── 5. Meteorologia ───────────────────────────────────────────────────────
    _section_heading(doc, '5. Meteorologia')
    fc_label = dict(BurningPlan.FIRE_CONDUCT_CHOICES if hasattr(BurningPlan, 'FIRE_CONDUCT_CHOICES')
                    else []).get(bp.fire_conduct, bp.fire_conduct)
    _two_col_table(doc, [
        (('Estado do tempo',        bp.weather_state),       ('Direção do vento',       bp.wind_direction)),
        (('Vel. vento (Beaufort)',   bp.wind_speed_beaufort), ('Vel. vento (km/h)',       bp.wind_speed_kmh)),
        (('Condução do fogo',        fc_label),               ('Descrição (se "Outro")',  bp.fire_conduct_other)),
    ])

    # ── 6. Efeitos e Eficácia ─────────────────────────────────────────────────
    _section_heading(doc, '6. Efeitos e Eficácia')
    t = doc.add_table(rows=2, cols=2)
    t.style = 'Table Grid'
    _label_cell(t.rows[0].cells[0], 'Efeitos da queima')
    _label_cell(t.rows[0].cells[1], 'Eficácia da ação')
    _value_cell(t.rows[1].cells[0], bp.burn_effects   or 'Não registado')
    _value_cell(t.rows[1].cells[1], bp.burn_efficiency or 'Não registado')
    doc.add_paragraph()

    # ── 7. Notas adicionais ───────────────────────────────────────────────────
    if bp.notes and bp.notes.strip():
        _section_heading(doc, '7. Notas Adicionais')
        t = doc.add_table(rows=1, cols=1)
        t.style = 'Table Grid'
        _value_cell(t.rows[0].cells[0], bp.notes)
        doc.add_paragraph()


    # ── 8. Esquema Tático ────────────────────────────────────────────────────
    _section_heading(doc, '8. Esquema Tático')
    schema_buf = _generate_parcela_schema(bp)
    if schema_buf:
        doc.add_picture(schema_buf, width=Cm(16))
        last_para = doc.paragraphs[-1]
        last_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    else:
        t = doc.add_table(rows=1, cols=1)
        t.style = 'Table Grid'
        _value_cell(t.rows[0].cells[0], 'Sem geometria de parcela disponível.')
    doc.add_paragraph()

    # ── 9. Assinaturas ────────────────────────────────────────────────────────
    _section_heading(doc, '9. Assinaturas')
    t = doc.add_table(rows=3, cols=2)
    t.style = 'Table Grid'
    _label_cell(t.rows[0].cells[0], 'Responsável da Queima')
    _label_cell(t.rows[0].cells[1], 'Técnico de Fogo Controlado')
    for cell in [t.rows[1].cells[0], t.rows[1].cells[1],
                 t.rows[2].cells[0], t.rows[2].cells[1]]:
        _set_cell_borders(cell)
        p = cell.paragraphs[0]
        r = p.add_run(' ')
        r.font.size = Pt(18)

    # ── Save to bytes ─────────────────────────────────────────────────────────
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
