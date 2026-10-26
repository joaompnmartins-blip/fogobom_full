"""
Load the official parish boundaries (CAOP, DGT) for mainland Portugal into
the Freguesia table, simplified to keep the table light, then fill the
concelho/freguesia/distrito of existing parcels.

    python manage.py load_caop                    # downloads CAOP 2025 (Continente)
    python manage.py load_caop --file caop.gpkg   # local GeoPackage or zip
"""
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from django.contrib.gis.gdal import DataSource
from django.contrib.gis.geos import MultiPolygon
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from parcelas.geo import apply_location
from parcelas.models import FireParcel, Freguesia

DEFAULT_URL = 'https://geo2.dgterritorio.gov.pt/caop/CAOP_Continente_2025-gpkg.zip'
LAYER = 'cont_freguesias'
SIMPLIFY_M = 5   # metres; plenty for locating parcels


class Command(BaseCommand):
    help = 'Load CAOP parish boundaries (mainland Portugal) and locate existing parcels.'

    def add_arguments(self, parser):
        parser.add_argument('--url', default=DEFAULT_URL)
        parser.add_argument('--file', help='Local .gpkg or .zip instead of downloading')

    def handle(self, *args, **opts):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(opts['file']) if opts['file'] else self.download(opts['url'], Path(tmp))
            gpkg = self.extract(src, Path(tmp))
            rows = self.read(gpkg)
        with transaction.atomic():
            Freguesia.objects.all().delete()
            Freguesia.objects.bulk_create(rows, batch_size=200)
        self.stdout.write(f'CAOP: {len(rows)} freguesias carregadas.')

        updated = 0
        for p in FireParcel.objects.all():
            if apply_location(p):
                p.save(update_fields=['concelho', 'freguesia', 'distrito'])
                updated += 1
        self.stdout.write(f'Parcelas localizadas: {updated}.')

    def download(self, url, tmp):
        self.stdout.write(f'A descarregar {url} …')
        dest = tmp / 'caop.zip'
        urllib.request.urlretrieve(url, dest)
        return dest

    def extract(self, src, tmp):
        if src.suffix.lower() == '.gpkg':
            return src
        with zipfile.ZipFile(src) as z:
            names = [n for n in z.namelist() if n.lower().endswith('.gpkg')]
            if not names:
                raise CommandError('O ficheiro não contém nenhum GeoPackage.')
            z.extract(names[0], tmp)
            return tmp / names[0]

    def read(self, gpkg):
        layer = DataSource(str(gpkg))[LAYER]
        rows = []
        for f in layer:
            g = f.geom.geos
            if g.srid != 3763:
                g.transform(3763)
            g = g.simplify(SIMPLIFY_M, preserve_topology=True)
            if g.geom_type == 'Polygon':
                g = MultiPolygon(g, srid=3763)
            rows.append(Freguesia(
                dicofre=f.get('dtmnfr'), freguesia=f.get('freguesia'), concelho=f.get('municipio'),
                distrito=f.get('distrito_ilha'), nuts3=f.get('nuts3') or '', geom=g,
            ))
        return rows
