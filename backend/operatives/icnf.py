"""
ICNF list of technicians credentialed in controlled burning ("Lista de Técnicos
Credenciados em Fogo Controlado", published as PDF): parsing and matching.
"""
import re
import unicodedata
from datetime import date, datetime

LINE_RE = re.compile(r'^(\d+-\d{4})\s+(.+?)\s+(Vitalícia|\d{2}/\d{2}/\d{4})\s*$')
NUMBER_RE = re.compile(r'^\d+-\d{4}$')
LIST_DATE_RE = re.compile(r'Atualização:\s*(\d{1,2}) de (\w+) de (\d{4})', re.IGNORECASE)
MONTHS = {m: i for i, m in enumerate(
    ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto',
     'setembro', 'outubro', 'novembro', 'dezembro'], start=1)}


def normalize_number(value):
    """'547/2026', ' 547 - 2026 ' → '547-2026'."""
    return re.sub(r'\s*[-/]\s*', '-', (value or '').strip())


def is_valid_number(value):
    return bool(NUMBER_RE.match(normalize_number(value)))


def _plain(text):
    text = unicodedata.normalize('NFKD', text.lower())
    return ''.join(c for c in text if not unicodedata.combining(c))


def parse_list_text(text):
    """Returns (list_date or None, [ {number, text, lifetime, valid_until} ])."""
    list_date = None
    m = LIST_DATE_RE.search(text)
    if m and m.group(2).lower() in MONTHS:
        list_date = date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)))
    rows = {}
    for line in text.splitlines():
        m = LINE_RE.match(line.strip())
        if not m:
            continue
        number, rest, validity = m.groups()
        lifetime = validity == 'Vitalícia'
        rows[number] = {
            'number': number,
            'text': rest.strip()[:200],
            'lifetime': lifetime,
            'valid_until': None if lifetime else datetime.strptime(validity, '%d/%m/%Y').date(),
        }
    return list_date, list(rows.values())


def parse_list_pdf(fileobj):
    from pypdf import PdfReader
    text = '\n'.join(page.extract_text() or '' for page in PdfReader(fileobj).pages)
    return parse_list_text(text)


def import_list(fileobj):
    """Replace the stored list with the one in `fileobj` (PDF). Returns (list_date, count)."""
    from django.db import transaction
    from .models import IcnfTechnician
    list_date, rows = parse_list_pdf(fileobj)
    if not rows:
        raise ValueError('Não foi encontrado nenhum técnico no ficheiro. Confirme que é a lista do ICNF em PDF.')
    with transaction.atomic():
        IcnfTechnician.objects.all().delete()
        IcnfTechnician.objects.bulk_create(IcnfTechnician(list_date=list_date, **r) for r in rows)
    return list_date, len(rows)


def match(number, full_name):
    """
    Compare a declared credential with the ICNF list.
    Returns dict(record, found, name_match): name_match is True when every
    word of the declared name (ignoring short connectors) appears in the list line.
    """
    from .models import IcnfTechnician
    record = IcnfTechnician.objects.filter(number=normalize_number(number)).first()
    if not record:
        return {'record': None, 'found': False, 'name_match': False}
    words = [w for w in re.findall(r'\w+', _plain(full_name)) if len(w) > 2]
    line = set(re.findall(r'\w+', _plain(record.text)))
    return {'record': record, 'found': True, 'name_match': bool(words) and all(w in line for w in words)}
